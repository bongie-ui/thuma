"""REAL rail: PayPal Payouts (sandbox). Pays suppliers, schools and funeral providers."""

from decimal import Decimal

from payments.paypal_client import PayPalError, get_client

from .base import Payee, Rail, RailError, RailResult, RailStatus, validate_amount

# PayPal batch_status values mapped onto our three-state flow.
_STATUS_MAP = {
    "PENDING": RailStatus.PENDING,
    "PROCESSING": RailStatus.PENDING,
    "SUCCESS": RailStatus.SUCCEEDED,
    "DENIED": RailStatus.FAILED,
    "CANCELED": RailStatus.FAILED,
}


class PayPalPayoutRail(Rail):
    name = "paypal_payouts"
    simulated = False

    def __init__(self, client=None):
        self.client = client

    def _client(self):
        return self.client or get_client()

    def pay(self, payee: Payee, amount: Decimal, reference: str, currency: str = "USD") -> RailResult:
        amount = validate_amount(amount)
        try:
            data = self._client().create_payout(
                receiver_email=payee.identifier,
                amount=amount,
                currency=currency,
                reference=reference,
                note=f"Thuma payment to {payee.name}",
            )
        except PayPalError as exc:
            raise RailError(str(exc)) from exc
        return self._result(data, reference)

    def status(self, external_id: str) -> RailResult:
        try:
            data = self._client().get_payout_batch(external_id)
        except PayPalError as exc:
            raise RailError(str(exc)) from exc
        return self._result(data, data.get("batch_header", {}).get("sender_batch_header", {}).get("sender_batch_id", ""))

    def _result(self, data, reference):
        header = data.get("batch_header", {})
        return RailResult(
            rail=self.name,
            reference=reference,
            external_id=header.get("payout_batch_id", ""),
            status=_STATUS_MAP.get(header.get("batch_status"), RailStatus.PENDING),
            simulated=False,
            raw=data,
        )
