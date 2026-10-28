"""SIMULATED last mile for the Local Mobile Money rail (BUILD_SPEC §8 step 2).

Starts once the payout to the provider succeeds. Airtime/bundles: DELIVERING -> DELIVERED after a few
seconds. Cash: AWAITING_COLLECTION with a 6-digit code sent to the beneficiary's chat -> COLLECTED.
"""

import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from mandates.models import LedgerEntry, Payee
from mandates.services import record

from .models import RailTransaction

DELIVERY_SECONDS = 3
CASH_PRODUCTS = ("cash",)
LAST_MILE_ACTOR = "SIMULATED_RAIL"


def _code():
    return f"{secrets.randbelow(10**6):06d}"


def _money(amount, currency):
    return f"${amount:.2f}" if currency == "USD" else f"{currency} {amount:.2f}"


def notify_beneficiary(request, text):
    """SMS-style notice in the beneficiary's chat (identified by their registered phone)."""
    from agent.models import ChatMessage, Conversation

    beneficiary = request.beneficiary
    if beneficiary is None:
        return None
    conversation, _ = Conversation.objects.get_or_create(
        family=beneficiary.family, participant_phone=beneficiary.phone, participant_user=None,
        defaults={"title": beneficiary.name})
    return ChatMessage.objects.create(conversation=conversation, role="assistant", text=text,
                                      linked_request=request)


@transaction.atomic
def start(tx, now=None):
    """Begin delivery for a succeeded provider payout. No-op for other rails or if already started."""
    tx = RailTransaction.objects.select_for_update().select_related("request__mandate", "request__beneficiary") \
        .get(pk=tx.pk)
    if tx.request.payee.rail != Payee.LOCAL_MOBILE_MONEY or tx.last_mile_status != RailTransaction.LAST_MILE_NA:
        return tx
    request = tx.request
    tx.raw = {**tx.raw, "last_mile_started_at": (now or timezone.now()).isoformat(), "simulated_last_mile": True}
    if request.product in CASH_PRODUCTS:
        tx.last_mile_status = RailTransaction.AWAITING_COLLECTION
        tx.collection_code = _code()
        notify_beneficiary(request, f"You have {_money(tx.amount, request.mandate.currency)} from your family. "
                                    f"Collect at any mobile money agent with code {tx.collection_code}.")
    else:
        tx.last_mile_status = RailTransaction.DELIVERING
    tx.save(update_fields=["last_mile_status", "collection_code", "raw", "updated_at"])
    return tx


@transaction.atomic
def advance(tx, now=None):
    """DELIVERING -> DELIVERED once DELIVERY_SECONDS have passed."""
    now = now or timezone.now()
    tx = RailTransaction.objects.select_for_update().select_related("request__mandate", "request__beneficiary") \
        .get(pk=tx.pk)
    if tx.last_mile_status != RailTransaction.DELIVERING:
        return tx
    started = datetime.fromisoformat(tx.raw["last_mile_started_at"])
    if now - started < timedelta(seconds=DELIVERY_SECONDS):
        return tx
    request = tx.request
    tx.last_mile_status = RailTransaction.DELIVERED
    tx.save(update_fields=["last_mile_status", "updated_at"])
    record(request.mandate, LedgerEntry.DELIVERED, LAST_MILE_ACTOR, request=request, amount=tx.amount,
           product=request.product, simulated=True)
    notify_beneficiary(request, f"Your {request.product} ({_money(tx.amount, request.mandate.currency)}) "
                                "from your family has arrived.")
    return tx


def advance_all(now=None):
    return [advance(tx, now) for tx in RailTransaction.objects.filter(last_mile_status=RailTransaction.DELIVERING)]


@transaction.atomic
def collect(tx, code=None):
    """Mark cash collected (demo button). If `code` is given it must match."""
    tx = RailTransaction.objects.select_for_update().select_related("request__mandate").get(pk=tx.pk)
    if tx.last_mile_status == RailTransaction.COLLECTED:
        return tx
    if tx.last_mile_status != RailTransaction.AWAITING_COLLECTION:
        raise ValueError("Nothing is waiting for collection")
    if code is not None and code != tx.collection_code:
        raise ValueError("Wrong collection code")
    tx.last_mile_status = RailTransaction.COLLECTED
    tx.save(update_fields=["last_mile_status", "updated_at"])
    record(tx.request.mandate, LedgerEntry.DELIVERED, LAST_MILE_ACTOR, request=tx.request, amount=tx.amount,
           product=tx.request.product, collected=True, simulated=True)
    return tx
