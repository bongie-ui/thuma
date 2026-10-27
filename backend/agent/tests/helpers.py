import itertools
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from mandates import services
from mandates.models import Request

_keys = itertools.count()


def midday():
    """Today 12:00 local time, so ODD_HOURS never fires by accident."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(12, 0)))


def quiet_ai(context):
    return {"ai_risk": 0, "flags": [], "summary": ""}


def submit(f, mandate, amount, product="", user=None, analyzer=quiet_ai, **kwargs):
    """Submit through the real pipeline with rails mocked (they return PENDING)."""
    kwargs.setdefault("beneficiary", f.beneficiary)
    kwargs.setdefault("payee", f.provider)
    if user is None and "requester_phone" not in kwargs:
        user = f.owner
    with mock.patch("payments.rails.for_payee") as for_payee:
        for_payee.return_value.pay.side_effect = fake_pay
        return services.submit_request(mandate=mandate, amount=Decimal(str(amount)), product=product,
                                       requester_user=user, idempotency_key=f"test-{next(_keys)}",
                                       intent_analyzer=analyzer, now=midday(), **kwargs)


def fake_pay(payee, amount, reference, currency="USD"):
    from payments.rails import RailResult, RailStatus
    return RailResult(rail="fake", reference=reference, external_id=f"EXT-{reference}",
                      status=RailStatus.PENDING, simulated=False)


def paid_history(f, mandate, amounts, product="bundles"):
    """Historical PAID requests for the beneficiary (AMOUNT_SPIKE baseline), dated in previous weeks."""
    for i, amount in enumerate(amounts, start=1):
        req = Request.objects.create(mandate=mandate, amount=Decimal(str(amount)), product=product,
                               beneficiary=f.beneficiary, payee=f.provider, requester_user=f.owner,
                               idempotency_key=f"hist-{next(_keys)}", status=Request.PAID)
        Request.objects.filter(pk=req.pk).update(created_at=midday() - timedelta(days=40 + 7 * i))
