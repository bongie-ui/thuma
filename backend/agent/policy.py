"""The policy engine (BUILD_SPEC §6). Pure and deterministic: the AI proposes, this code decides.

`check(request)` computes a decision without writing anything; `evaluate(request)` persists it.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from mandates import signing
from mandates.models import Decision, Evidence, LedgerEntry, Mandate, Request, RiskAssessment
from mandates.services import mandate_balance, record
from mandates.templates import SOFT_RULES

_OUTCOME_STATUS = {
    Decision.APPROVE: Request.APPROVED,
    Decision.REFUSE: Request.REFUSED,
    Decision.ESCALATE: Request.ESCALATED,
    Decision.HOLD_FRAUD: Request.HELD_FRAUD,
}


@dataclass
class PolicyResult:
    outcome: str
    reason: str
    rule_results: list = field(default_factory=list)


def money(amount, currency="USD"):
    amount = Decimal(str(amount))
    return f"${amount:.2f}" if currency == "USD" else f"{currency} {amount:.2f}"


def person(request):
    user = request.requester_user
    if user is not None:
        return user.get_full_name() or user.first_name or user.username
    return request.requester_display or request.requester_phone or "someone"


def period_start(period, now):
    local = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return local - timedelta(days=local.weekday())
    if period == "month":
        return local.replace(day=1)
    if period == "year":
        return local.replace(month=1, day=1)
    return local


def _committed(request):
    return Request.objects.filter(mandate=request.mandate, status__in=Request.COMMITTED).exclude(pk=request.pk)


def _latest_evidence(request, kinds):
    return request.evidence.filter(kind__in=kinds).order_by("-created_at").first()


# --- Rule checks: (rule, request, ctx) -> (passed, detail) ------------------------------------------------

def _allowed_payees(rule, request, ctx):
    ok = request.payee_id is not None and str(request.payee_id) in map(str, rule.params["payee_ids"])
    name = request.payee.name if request.payee else "no payee"
    return ok, f"{name} is an approved payee" if ok else f"{name} is not an approved payee for this mandate"


def _allowed_beneficiaries(rule, request, ctx):
    ok = request.beneficiary_id is not None and \
        str(request.beneficiary_id) in map(str, rule.params["beneficiary_ids"])
    name = request.beneficiary.name if request.beneficiary else "No beneficiary"
    return ok, f"{name} is covered" if ok else f"{name} is not covered by this mandate"


def _allowed_products(rule, request, ctx):
    product = request.product
    if product not in rule.params["products"]:
        return False, f"\"{product or 'unspecified'}\" is not allowed by this mandate"
    if request.beneficiary and product not in (request.beneficiary.allowed_products or []):
        return False, f"\"{product}\" is not allowed for {request.beneficiary.name}"
    return True, f"\"{product}\" is allowed"


def _max_per_request(rule, request, ctx):
    limit = Decimal(str(rule.params["amount"]))
    ok = request.amount <= limit
    return ok, (f"{money(request.amount, ctx['currency'])} is within the {money(limit, ctx['currency'])} "
                "per-request limit" if ok else
                f"{money(request.amount, ctx['currency'])} is over the {money(limit, ctx['currency'])} "
                "per-request limit")


def _applies_to_product(rule, request):
    product = rule.params.get("product")
    return not product or product == request.product


def _cap_per_period(rule, request, ctx):
    if not _applies_to_product(rule, request):
        return True, "Does not apply to this product"
    cap = Decimal(str(rule.params["amount"]))
    period = rule.params["period"]
    product = rule.params.get("product")
    qs = _committed(request).filter(created_at__gte=period_start(period, ctx["now"]))
    if product:
        qs = qs.filter(product=product)
    if not rule.params.get("shared"):
        qs = qs.filter(requester_user=request.requester_user) if request.requester_user_id else \
            qs.filter(requester_phone=request.requester_phone)
    used = sum((r.amount for r in qs), Decimal("0"))
    label = f"{product} " if product else ""
    scope = "shared by all funders" if rule.params.get("shared") else "for you"
    cur = ctx["currency"]
    if used + request.amount <= cap:
        return True, f"{money(used, cur)} of the {money(cap, cur)} {label}cap this {period} used ({scope})"
    return False, (f"This would go over the {money(cap, cur)} {label}cap this {period} ({scope}): "
                   f"{money(used, cur)} already used, {money(cap - used, cur)} left")


def _min_interval(rule, request, ctx):
    if not _applies_to_product(rule, request):
        return True, "Does not apply to this product"
    hours = rule.params["hours"]
    qs = _committed(request).filter(created_at__gte=ctx["now"] - timedelta(hours=hours))
    if rule.params.get("product"):
        qs = qs.filter(product=rule.params["product"])
    else:
        qs = qs.filter(product=request.product)
    if request.beneficiary_id:
        qs = qs.filter(beneficiary_id=request.beneficiary_id)
    last = qs.select_related("requester_user").order_by("-created_at").first()
    if last is None:
        return True, f"No {request.product or 'payment'} in the last {hours} hours"
    when = timezone.localtime(last.created_at).strftime("%H:%M on %d %b")
    return False, (f"{person(last)} already sent {request.product or 'this'} ({money(last.amount, ctx['currency'])}) "
                   f"at {when}; wait {hours} hours between top-ups")


def _requires_evidence(rule, request, ctx):
    kind = rule.params["kind"]
    label = rule.params.get("label") or kind.replace("_", " ").lower()
    evidence = _latest_evidence(request, [kind])
    if evidence is None:
        return False, f"Needs evidence: {label}"
    if kind == Evidence.MILESTONE_PHOTO:
        verdict = (evidence.extracted or {}).get("verdict")
        if verdict != "matches":
            observed = (evidence.extracted or {}).get("observed", "")
            return False, f"The photo does not show {label} (verdict: {verdict or 'not read yet'}). {observed}".strip()
    elif not evidence.extracted:
        return False, f"The {label} has not been read yet"
    return True, f"Evidence provided: {label}"


def _price_ceiling(rule, request, ctx):
    item = rule.params["item"]
    keywords = [k.lower() for k in rule.params.get("keywords") or [item.split("_")[0]]]
    limit = Decimal(str(rule.params["max_unit_price"]))
    evidence = _latest_evidence(request, [Evidence.QUOTE, Evidence.INVOICE])
    items = (evidence.extracted or {}).get("items") if evidence else None
    if not items:
        return False, "Needs a quote or invoice with line items to check prices"
    pretty = item.replace("_", " ")
    matched = [line for line in items
               if line.get("key") == item or any(k in str(line.get("name", "")).lower() for k in keywords)]
    if not matched:
        return True, f"No {pretty} on the quote"
    for line in matched:
        price = Decimal(str(line.get("unit_price", 0)))
        if price > limit:
            return False, (f"{line.get('name', pretty)} is quoted at {money(price, ctx['currency'])} each; "
                           f"the limit is {money(limit, ctx['currency'])}")
    return True, f"All {pretty} prices are within {money(limit, ctx['currency'])}"


def _requires_invoice(rule, request, ctx):
    invoice = _latest_evidence(request, [Evidence.INVOICE])
    if invoice is None or not invoice.extracted:
        return False, "Needs the payee's invoice"
    data = invoice.extracted
    try:
        total = Decimal(str(data.get("total")))
    except Exception:
        return False, "The invoice total could not be read"
    if total != request.amount:
        return False, (f"The invoice total ({money(total, ctx['currency'])}) does not match the request "
                       f"({money(request.amount, ctx['currency'])})")
    supplier = str(data.get("supplier", "")).strip().lower()
    payee = request.payee.name.lower() if request.payee else ""
    if not supplier or not payee or (supplier not in payee and payee not in supplier):
        return False, f"The invoice is from \"{data.get('supplier', 'unknown')}\", not the payee"
    return True, f"Invoice from {request.payee.name} for {money(total, ctx['currency'])}"


def _escalate_above(rule, request, ctx):
    limit = Decimal(str(rule.params["amount"]))
    if request.amount > limit:
        return False, f"Over {money(limit, ctx['currency'])}, so a funder must approve"
    return True, f"Within {money(limit, ctx['currency'])}, no approval needed"


_auto_approve_below = _escalate_above

RULE_CHECKS = {
    "allowed_payees": _allowed_payees,
    "allowed_beneficiaries": _allowed_beneficiaries,
    "allowed_products": _allowed_products,
    "max_per_request": _max_per_request,
    "cap_per_period": _cap_per_period,
    "min_interval": _min_interval,
    "requires_evidence": _requires_evidence,
    "price_ceiling": _price_ceiling,
    "requires_invoice": _requires_invoice,
    "escalate_above": _escalate_above,
    "auto_approve_below": _auto_approve_below,
}


def precheck(request, now=None):
    """Mandate-level checks (signature, status, expiry, balance). Returns a refusal reason or None."""
    now = now or timezone.now()
    mandate = Mandate.objects.get(pk=request.mandate_id)  # stored state, never a stale in-memory copy
    if not signing.verify(mandate):
        return "The mandate's rules do not match its signature, so nothing can be paid until the owner re-confirms them"
    if mandate.status != Mandate.ACTIVE:
        return f"The mandate is {mandate.get_status_display().lower()}"
    if mandate.expires_at and mandate.expires_at <= now:
        return "The mandate has expired"
    if request.amount <= 0:
        return "The amount must be positive"
    balance = mandate_balance(mandate, exclude_request=request)
    if request.amount > balance:
        return f"Insufficient mandate funds: {money(balance, mandate.currency)} available"
    return None


def check(request, now=None, funder_verified=False):
    """Compute the decision for `request`. Requires a RiskAssessment (fraud.assess runs first).

    HIGH risk holds the request even when a rule also fails, so funders always see the fraud card.
    `funder_verified=True` re-checks after a funder approved or verified it: risk and soft rules are then
    satisfied by that funder, but every hard rule, the signature and the balance still apply.
    """
    now = now or timezone.now()
    if refusal := precheck(request, now):
        return PolicyResult(Decision.REFUSE, refusal, [{"rule_id": None, "kind": "mandate", "passed": False,
                                                        "detail": refusal}])
    ctx = {"now": now, "currency": request.mandate.currency}
    results = []
    for rule in request.mandate.rules.all():
        checker = RULE_CHECKS.get(rule.kind)
        if checker is None:
            passed, detail = False, f"Unknown rule kind {rule.kind}"
        else:
            passed, detail = checker(rule, request, ctx)
        results.append({"rule_id": str(rule.id), "kind": rule.kind, "passed": passed, "detail": detail})

    hard_failures = [r for r in results if not r["passed"] and r["kind"] not in SOFT_RULES]
    soft_triggers = [r for r in results if not r["passed"] and r["kind"] in SOFT_RULES]
    try:
        risk = request.risk_assessment
    except RiskAssessment.DoesNotExist:
        raise ValueError("fraud.assess must run before the policy engine")

    if risk.level == RiskAssessment.HIGH and not funder_verified:
        return PolicyResult(Decision.HOLD_FRAUD, f"Held: possible fraud (risk score {risk.score}). "
                                                 "A funder must verify with the beneficiary on the registered number",
                            results)
    if hard_failures:
        return PolicyResult(Decision.REFUSE, "Refused: " + "; ".join(r["detail"] for r in hard_failures), results)
    if funder_verified:
        return PolicyResult(Decision.APPROVE, "Approved by a funder; all rules passed", results)
    if risk.level == RiskAssessment.MEDIUM:
        return PolicyResult(Decision.ESCALATE, f"A funder must approve: some risk signals (score {risk.score})",
                            results)
    if soft_triggers:
        return PolicyResult(Decision.ESCALATE, "; ".join(r["detail"] for r in soft_triggers), results)
    return PolicyResult(Decision.APPROVE, "Approved: all rules passed", results)


@transaction.atomic
def evaluate(request, now=None):
    """Decide, then write the Decision, a DECIDED ledger entry and the request's new status."""
    result = check(request, now)
    decision = Decision.objects.create(request=request, outcome=result.outcome, reason=result.reason,
                                       rule_results=result.rule_results, decided_by=Decision.POLICY)
    request.status = _OUTCOME_STATUS[result.outcome]
    request.save(update_fields=["status", "updated_at"])
    record(request.mandate, LedgerEntry.DECIDED, Decision.POLICY, request=request, amount=request.amount,
           outcome=result.outcome, reason=result.reason)
    return decision
