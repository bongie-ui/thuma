"""State changes for mandates. Views, the agent and seed_demo go through these functions, never raw saves.

Every state change writes an append-only LedgerEntry.
"""

import hashlib
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Membership
from core.phones import find_phones, normalize_phone

from . import signing
from .models import (Approval, Beneficiary, BlockedPhone, Decision, Funding, LedgerEntry, Mandate, MandateFunder,
                     Payee, Request, Rule, Upload)
from .templates import validate_rules

SYSTEM = "SYSTEM"


class ServiceError(Exception):
    """A request the caller made that the rules do not allow; message is safe to show to users."""


def actor_of(user):
    return str(user.pk) if user is not None else SYSTEM


def record(mandate, event, actor, request=None, amount=None, **data):
    return LedgerEntry.objects.create(family_id=mandate.family_id, mandate=mandate, request=request,
                                      event=event, amount=amount, actor=actor, data=data)


def membership(user, family):
    return Membership.objects.filter(user=user, family=family).first()


def require_funder(user, family):
    m = membership(user, family)
    if m is None or not m.can_fund:
        raise ServiceError("Only the family's funders can do this")
    return m


# --- Mandates ---------------------------------------------------------------------------------------------

def _normalise_rules(rules):
    return [{"kind": r["kind"], "params": r.get("params") or {}, "position": i} for i, r in enumerate(rules)]


@transaction.atomic
def create_mandate(*, family, type, title, rules, created_by, purpose_text="", currency="USD", expires_at=None,
                   co_funders=()):
    """Validate rules against the template, save, sign and activate. `created_by` becomes the OWNER."""
    require_funder(created_by, family)
    rules = _normalise_rules(rules)
    if errors := validate_rules(type, rules):
        raise ServiceError("; ".join(errors))
    mandate = Mandate.objects.create(family=family, type=type, title=title, purpose_text=purpose_text,
                                     currency=currency, expires_at=expires_at, created_by=created_by,
                                     status=Mandate.ACTIVE)
    Rule.objects.bulk_create(Rule(mandate=mandate, **r) for r in rules)
    MandateFunder.objects.create(mandate=mandate, user=created_by, role=MandateFunder.OWNER)
    for user in co_funders:
        add_funder(mandate, user, added_by=created_by)
    mandate.signature = signing.sign(mandate)
    mandate.save(update_fields=["signature", "updated_at"])
    record(mandate, LedgerEntry.RULES_CHANGED, actor_of(created_by), version=mandate.version, created=True,
           rules=rules)
    return mandate


def add_funder(mandate, user, added_by):
    require_funder(user, mandate.family)
    funder, _ = MandateFunder.objects.get_or_create(mandate=mandate, user=user,
                                                    defaults={"role": MandateFunder.CO_FUNDER})
    return funder


def is_owner(mandate, user):
    return MandateFunder.objects.filter(mandate=mandate, user=user, role=MandateFunder.OWNER).exists()


@transaction.atomic
def update_rules(mandate, rules, user):
    """Replace the rule set: owner only, bumps the version, re-signs and records the change."""
    if not is_owner(mandate, user):
        raise ServiceError("Only the mandate owner can change its rules")
    rules = _normalise_rules(rules)
    if errors := validate_rules(mandate.type, rules):
        raise ServiceError("; ".join(errors))
    mandate.rules.all().delete()
    Rule.objects.bulk_create(Rule(mandate=mandate, **r) for r in rules)
    mandate.version += 1
    mandate.signature = signing.sign(mandate)
    mandate.save(update_fields=["version", "signature", "updated_at"])
    record(mandate, LedgerEntry.RULES_CHANGED, actor_of(user), version=mandate.version, rules=rules)
    return mandate


# --- Funding and balances ---------------------------------------------------------------------------------

def create_funding(mandate, funder, amount, rail=Funding.PAYPAL, external_id=""):
    if mandate.status != Mandate.ACTIVE:
        raise ServiceError("This mandate is not accepting funds")
    if funder is not None and not mandate.mandate_funders.filter(user=funder).exists():
        raise ServiceError("Only this mandate's funders can fund it")
    amount = Decimal(amount)
    if amount <= 0:
        raise ServiceError("Amount must be positive")
    return Funding.objects.create(mandate=mandate, funder=funder, amount=amount, rail=rail, external_id=external_id)


@transaction.atomic
def mark_funding_captured(funding, external_id=None):
    """Idempotent: capturing twice records one FUNDED entry."""
    funding = Funding.objects.select_for_update().get(pk=funding.pk)
    if funding.status == Funding.CAPTURED:
        return funding
    funding.status = Funding.CAPTURED
    if external_id:
        funding.external_id = external_id
    funding.save(update_fields=["status", "external_id", "updated_at"])
    record(funding.mandate, LedgerEntry.FUNDED, actor_of(funding.funder), amount=funding.amount,
           funding_id=str(funding.id), rail=funding.rail, external_id=funding.external_id)
    return funding


def captured_total(mandate):
    return mandate.fundings.filter(status=Funding.CAPTURED).aggregate(t=Sum("amount"))["t"] or Decimal("0")


def committed_total(mandate, exclude_request=None):
    qs = mandate.requests.filter(status__in=Request.COMMITTED)
    if exclude_request is not None:
        qs = qs.exclude(pk=exclude_request.pk)
    return qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")


def mandate_balance(mandate, exclude_request=None):
    """Captured funding minus approved (payout pending) and paid requests."""
    return captured_total(mandate) - committed_total(mandate, exclude_request)


def funder_contributions(mandate):
    """{user_id: captured amount} for every funder of the mandate (zero if they have not funded yet)."""
    totals = {f.user_id: Decimal("0") for f in mandate.mandate_funders.all()}
    for row in mandate.fundings.filter(status=Funding.CAPTURED, funder__isnull=False) \
            .values("funder_id").annotate(t=Sum("amount")):
        totals[row["funder_id"]] = row["t"]
    return totals


# --- Beneficiaries ----------------------------------------------------------------------------------------

def register_beneficiary(*, family, name, phone, registered_by, relationship="", allowed_products=()):
    require_funder(registered_by, family)
    e164 = normalize_phone(phone)
    if not e164:
        raise ServiceError("Enter a valid phone number")
    return Beneficiary.objects.create(family=family, name=name, phone=e164, relationship=relationship,
                                      allowed_products=list(allowed_products), registered_by=registered_by,
                                      verified_at=timezone.now())


def change_beneficiary_phone(beneficiary, phone, user):
    """Changing a number triggers the BENEFICIARY_RECENTLY_CHANGED fraud signal for 72 hours."""
    require_funder(user, beneficiary.family)
    e164 = normalize_phone(phone)
    if not e164:
        raise ServiceError("Enter a valid phone number")
    if e164 != beneficiary.phone:
        beneficiary.phone = e164
        beneficiary.phone_changed_at = timezone.now()
        beneficiary.save(update_fields=["phone", "phone_changed_at", "updated_at"])
    return beneficiary


# --- Requests: assess -> decide -> execute ----------------------------------------------------------------

def _intent_analyzer():
    from agent import fraud
    return fraud.default_intent_analyzer()


ALLOWED_UPLOAD_TYPES = Upload.IMAGE_TYPES + ("application/pdf",)


def create_upload(*, family, data, content_type, name="", user=None, phone=""):
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise ServiceError("Send a photo (JPEG, PNG, WebP) or a PDF")
    if not data:
        raise ServiceError("The file is empty")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise ServiceError("The file is too large (8 MB maximum)")
    return Upload.objects.create(family=family, uploaded_by=user, uploaded_by_phone=normalize_phone(phone) or phone,
                                 name=name[:200], content_type=content_type, size=len(data),
                                 sha256=hashlib.sha256(data).hexdigest(), data=data)


def _extract(evidence):
    from agent import extraction
    return extraction.extract(evidence)


def attach_evidence(request, upload, kind, extractor=None):
    """Attach an uploaded file as evidence and read it. A failed read leaves the evidence unread,
    which the rules treat as missing — never as passed."""
    from agent.extraction import ExtractionError
    from agent.llm import LLMError

    if upload.family_id != request.mandate.family_id:
        raise ServiceError("That file belongs to another family")
    evidence = request.evidence.create(kind=kind, upload=upload)
    try:
        (extractor or _extract)(evidence)
    except (ExtractionError, LLMError) as exc:
        evidence.extracted = {}
        evidence.model_name = ""
        evidence.save(update_fields=["extracted", "model_name", "updated_at"])
        evidence.error = str(exc)
    return evidence


@transaction.atomic
def submit_request(*, mandate, amount, idempotency_key, channel=Request.APP, requester_user=None,
                   requester_phone="", requester_display="", beneficiary=None, payee=None, product="",
                   message_text="", evidence=(), uploads=(), summary_en="", intent_analyzer=None, extractor=None,
                   now=None):
    """Create a Request, then run fraud.assess -> policy.evaluate -> execute_decision.

    Creating a request never pays by itself; only an APPROVE decision leads to a payout.
    Re-submitting the same idempotency_key returns the existing request untouched.
    `evidence` is a list of {"kind", "extracted"} dicts and `uploads` a list of (Upload, kind) pairs, both
    attached (uploads are read by the vision model) before the policy runs.
    """
    from agent import fraud, policy

    existing = Request.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if requester_user is not None and membership(requester_user, mandate.family) is None:
        raise ServiceError("You are not a member of this family")
    request = Request.objects.create(
        mandate=mandate, amount=Decimal(amount), idempotency_key=idempotency_key, channel=channel,
        requester_user=requester_user, requester_phone=normalize_phone(requester_phone) or requester_phone,
        requester_display=requester_display, beneficiary=beneficiary, payee=payee, product=product,
        message_text=message_text, summary_en=summary_en)
    record(mandate, LedgerEntry.REQUESTED, actor_of(requester_user) if requester_user else
           (request.requester_phone or SYSTEM), request=request, amount=request.amount, product=product,
           channel=channel)
    for item in evidence:
        request.evidence.create(kind=item["kind"], extracted=item.get("extracted") or {},
                                model_name=item.get("model_name", ""))
    for upload, kind in uploads:
        attach_evidence(request, upload, kind, extractor=extractor)

    risk = fraud.assess(request, intent_analyzer=intent_analyzer or _intent_analyzer(), now=now)
    request.status = Request.ASSESSED
    request.save(update_fields=["status", "updated_at"])
    record(mandate, LedgerEntry.ASSESSED, "POLICY", request=request, score=risk.score, level=risk.level,
           signals=[s["signal"] for s in risk.signals], ai_flags=[f["flag"] for f in risk.ai_flags])

    policy.evaluate(request, now=now)
    execute_decision(request)
    request.refresh_from_db()
    return request


def reassess(request, intent_analyzer=None, now=None):
    """Re-run assessment and policy after new evidence (e.g. a revised quote). Only for undecided or
    refused requests; never touches a request that is paid, pending payment or held for fraud."""
    from agent import fraud, policy

    if request.status not in (Request.NEW, Request.ASSESSED, Request.REFUSED):
        raise ServiceError("This request can no longer be re-checked")
    fraud.assess(request, intent_analyzer=intent_analyzer or _intent_analyzer(), now=now)
    policy.evaluate(request, now=now)
    execute_decision(request)
    request.refresh_from_db()
    return request


def sole_payee(mandate):
    """The mandate's only allowed payee, e.g. the mobile money provider of a support mandate; else None."""
    from .models import Payee

    ids = {str(i) for r in mandate.rules.all() if r.kind == "allowed_payees" for i in r.params.get("payee_ids", [])}
    return Payee.objects.filter(pk=next(iter(ids))).first() if len(ids) == 1 else None


def execute_decision(request):
    """Act on the latest policy decision: pay on APPROVE; ESCALATED / HELD_FRAUD wait in the funders' inbox."""
    from payments.payouts import pay_request

    if request.status == Request.APPROVED:
        return pay_request(request)
    if request.status == Request.HELD_FRAUD:
        risk = request.risk_assessment
        record(request.mandate, LedgerEntry.FRAUD_HELD, "POLICY", request=request, amount=request.amount,
               score=risk.score, signals=[s["signal"] for s in risk.signals])
    return None


def inbox(user):
    """Requests waiting for this funder: escalations and fraud holds on mandates they fund."""
    return Request.objects.filter(mandate__mandate_funders__user=user,
                                  status__in=(Request.ESCALATED, Request.HELD_FRAUD)) \
        .select_related("mandate", "beneficiary", "payee").order_by("-created_at")


ALLOWED_ACTIONS = {
    Request.ESCALATED: {Approval.APPROVE, Approval.REJECT, Approval.REPORT_FRAUD},
    Request.HELD_FRAUD: {Approval.VERIFIED_SAFE, Approval.REJECT, Approval.REPORT_FRAUD},
}


@transaction.atomic
def apply_approval(request, user, action, note=""):
    """A funder's answer to an escalation or fraud hold. Hard refusals cannot be overridden."""
    from agent import fraud, policy

    request = Request.objects.select_for_update().get(pk=request.pk)
    if not request.mandate.mandate_funders.filter(user=user).exists():
        raise ServiceError("Only this mandate's funders can approve its requests")
    allowed = ALLOWED_ACTIONS.get(request.status)
    if allowed is None:
        raise ServiceError(f"This request is {request.get_status_display().lower()} and cannot be approved "
                           "or rejected" + (" (a refusal needs a rule change)" if request.status == Request.REFUSED
                                            else ""))
    if action not in allowed:
        raise ServiceError(f"{action} is not possible for a request that is {request.get_status_display().lower()}")
    if action == Approval.VERIFIED_SAFE and not note.strip():
        raise ServiceError("Say how you verified it, e.g. that you called the beneficiary on the registered number")

    Approval.objects.create(request=request, user=user, action=action, note=note)
    actor = actor_of(user)

    if action in (Approval.APPROVE, Approval.VERIFIED_SAFE):
        record(request.mandate, LedgerEntry.APPROVED_BY_FUNDER, actor, request=request, amount=request.amount,
               action=action, note=note)
        result = policy.check(request, funder_verified=True)
        Decision.objects.create(request=request, outcome=result.outcome, reason=result.reason,
                                rule_results=result.rule_results, decided_by=actor)
        request.status = Request.APPROVED if result.outcome == Decision.APPROVE else Request.REFUSED
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.DECIDED, actor, request=request, amount=request.amount,
               outcome=result.outcome, reason=result.reason)
        execute_decision(request)
    elif action == Approval.REJECT:
        Decision.objects.create(request=request, outcome=Decision.REFUSE, reason=f"Rejected by a funder. {note}".strip(),
                                decided_by=actor)
        request.status = Request.REFUSED
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.DECIDED, actor, request=request, amount=request.amount,
               outcome=Decision.REFUSE, note=note)
    else:  # REPORT_FRAUD
        registered = fraud.registered_phones(request.mandate.family)
        suspects = [p for p in [request.requester_phone, *find_phones(request.message_text)]
                    if p and p not in registered]
        for phone in dict.fromkeys(suspects):
            BlockedPhone.objects.get_or_create(family=request.mandate.family, phone=phone,
                                               defaults={"reason": note, "request": request})
        request.status = Request.CONFIRMED_FRAUD
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.FRAUD_CONFIRMED, actor, request=request, amount=request.amount,
               blocked=suspects, note=note)
    request.refresh_from_db()
    return request
