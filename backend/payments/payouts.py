"""Moving money for an approved Request. Only mandates.services calls this, after a policy APPROVE
(or a funder approval that passed the policy re-check)."""

from django.db import transaction

from mandates.models import LedgerEntry, Request
from mandates.services import record

from . import last_mile, rails
from .models import RailTransaction

PAYPAL = "PAYPAL"
_RAIL_STATUS = {
    rails.RailStatus.PENDING: RailTransaction.PENDING,
    rails.RailStatus.SUCCEEDED: RailTransaction.SUCCESS,
    rails.RailStatus.FAILED: RailTransaction.FAILED,
}


def reference_for(request):
    """Idempotency key: PayPal rejects a second batch with the same sender_batch_id."""
    return f"thuma-{request.id}"


def _identifier(request):
    payee = request.payee
    beneficiary_phone = request.beneficiary.phone if request.beneficiary else ""
    return payee.paypal_email or payee.external_ref or beneficiary_phone


@transaction.atomic
def pay_request(request):
    """Pay an APPROVED request once. A second call returns the existing transaction."""
    request = Request.objects.select_for_update().get(pk=request.pk)
    existing = request.rail_transactions.exclude(status=RailTransaction.FAILED).first()
    if existing is not None:
        return existing
    if request.status != Request.APPROVED:
        raise ValueError(f"Only approved requests can be paid (status {request.status})")
    if request.payee is None:
        raise ValueError("Request has no payee")

    reference = reference_for(request)
    try:
        rail = rails.for_payee(request.payee)
        result = rail.pay(rails.Payee(request.payee.name, _identifier(request)), request.amount, reference,
                          currency=request.mandate.currency)
    except rails.RailError as exc:
        tx = RailTransaction.objects.create(request=request, rail=request.payee.rail, amount=request.amount,
                                            reference=reference, status=RailTransaction.FAILED,
                                            raw={"error": str(exc)})
        _set_request(request, Request.FAILED)
        record(request.mandate, LedgerEntry.FAILED, "SYSTEM", request=request, amount=request.amount,
               rail=tx.rail, error=str(exc))
        return tx

    tx = RailTransaction.objects.create(request=request, rail=request.payee.rail, amount=request.amount,
                                        reference=reference, external_id=result.external_id,
                                        simulated=result.simulated, raw=result.raw,
                                        status=RailTransaction.PENDING)
    apply_rail_status(tx, _RAIL_STATUS.get(result.status, RailTransaction.PENDING))
    return tx


def _set_request(request, status):
    request.status = status
    request.save(update_fields=["status", "updated_at"])


@transaction.atomic
def apply_rail_status(tx, status, raw=None):
    """Move a RailTransaction to `status` (from webhooks, polling or the rail itself). Idempotent."""
    tx = RailTransaction.objects.select_for_update().select_related("request__mandate").get(pk=tx.pk)
    if raw:
        tx.raw = {**tx.raw, "last_update": raw}
    if tx.status == status:
        tx.save(update_fields=["raw", "updated_at"])
        return tx
    tx.status = status
    tx.save(update_fields=["status", "raw", "updated_at"])
    request = tx.request
    actor = "SYSTEM" if tx.simulated else PAYPAL
    if status == RailTransaction.SUCCESS:
        _set_request(request, Request.PAID)
        record(request.mandate, LedgerEntry.PAID, actor, request=request, amount=tx.amount, rail=tx.rail,
               external_id=tx.external_id, simulated=tx.simulated)
        last_mile.start(tx)
    elif status in (RailTransaction.FAILED, RailTransaction.RETURNED):
        _set_request(request, Request.FAILED)
        record(request.mandate, LedgerEntry.FAILED, actor, request=request, amount=tx.amount, rail=tx.rail,
               external_id=tx.external_id, status=status)
    return tx
