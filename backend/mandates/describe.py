"""Plain-words views of mandates for people: rule sentences and "what's covered this period"."""

import uuid

from django.utils import timezone

from agent.policy import money, period_start, person

from .models import Beneficiary, Evidence, Payee, Request

_EVIDENCE = dict(Evidence.KINDS)
_PER = {"day": "a day", "week": "a week", "month": "a month", "year": "a year"}


def _names(model, ids):
    names = dict(model.objects.filter(pk__in=ids).values_list("id", "name"))
    return ", ".join(names.get(_uuid(i), "an unknown entry") for i in ids)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return value


def _product(params, fallback="all spending"):
    return params.get("product") or fallback


def describe_rule(kind, params, currency="USD"):
    """One sentence for a rule. Unknown kinds are shown as-is rather than hidden."""
    p = params or {}
    if kind == "allowed_payees":
        return f"Pays only {_names(Payee, p.get('payee_ids', []))}"
    if kind == "allowed_beneficiaries":
        return f"Only for {_names(Beneficiary, p.get('beneficiary_ids', []))}"
    if kind == "allowed_products":
        return f"Allowed: {', '.join(p.get('products', []))}"
    if kind == "max_per_request":
        return f"At most {money(p['amount'], currency)} per request"
    if kind == "cap_per_period":
        shared = " shared by all funders" if p.get("shared") else ""
        return f"{_product(p).capitalize()}: up to {money(p['amount'], currency)} {_PER.get(p['period'], p['period'])}{shared}"
    if kind == "min_interval":
        return f"{_product(p, 'Requests').capitalize()}: at most once every {p['hours']} hours"
    if kind == "requires_evidence":
        label = f" ({p['label']})" if p.get("label") else ""
        return f"Needs a {_EVIDENCE.get(p['kind'], p['kind']).lower()}{label} that the agent has checked"
    if kind == "price_ceiling":
        return f"{p['item'].replace('_', ' ').capitalize()}: no more than {money(p['max_unit_price'], currency)} each"
    if kind == "requires_invoice":
        return "Needs the payee's invoice for the exact amount"
    if kind == "escalate_above":
        return f"A funder must approve anything over {money(p['amount'], currency)}"
    if kind == "auto_approve_below":
        return f"Paid automatically only below {money(p['amount'], currency)}; above that a funder approves"
    return f"{kind}: {p}"


def coverage(mandate, beneficiary, now=None):
    """Per allowed product: the period cap, what is used, and who covered it (for the quick actions)."""
    now = now or timezone.now()
    rules = list(mandate.rules.all())
    products = next((r.params.get("products", []) for r in rules if r.kind == "allowed_products"), [])
    products = [x for x in products if x in (beneficiary.allowed_products or [])]
    result = []
    for product in products:
        cap = next((r.params for r in rules if r.kind == "cap_per_period" and r.params.get("product") == product), None)
        interval = next((r.params for r in rules if r.kind == "min_interval" and r.params.get("product") == product),
                        None)
        since = period_start(cap["period"], now) if cap else period_start("month", now)
        paid = Request.objects.filter(mandate=mandate, beneficiary=beneficiary, product=product,
                                      status__in=Request.COMMITTED, created_at__gte=since) \
            .select_related("requester_user").order_by("-created_at")
        used = sum((r.amount for r in paid), start=0)
        result.append({
            "product": product,
            "period": cap["period"] if cap else "month",
            "cap": str(cap["amount"]) if cap else None,
            "used": f"{used:.2f}",
            "min_interval_hours": interval["hours"] if interval else None,
            "covered_by": [{"request_id": str(r.id), "by": person(r), "amount": str(r.amount),
                            "at": r.created_at.isoformat(), "status": r.status} for r in paid],
            "summary": _summary(product, paid, mandate.currency),
        })
    return result


def _summary(product, paid, currency):
    if not paid:
        return f"No {product} sent yet this period"
    latest = paid[0]
    when = timezone.localtime(latest.created_at)
    return f"{person(latest)} sent {money(latest.amount, currency)} of {product} on {when:%d %b at %H:%M}"
