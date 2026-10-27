"""Mandate types as rule templates + data (BUILD_SPEC §5).

Core logic must not branch on the mandate type. A type is a label, the rule kinds it must contain,
and default rules the drafting agent fills in. Funding is always through PayPal.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .models import Evidence, Mandate, Payee

# Funding methods (money in). PayPal is the central rail; Paynow test mode is inbound-only for pools.
PAYPAL_CHECKOUT = "PAYPAL_CHECKOUT"
PAYPAL_SUBSCRIPTIONS = "PAYPAL_SUBSCRIPTIONS"
PAYNOW_INBOUND = "PAYNOW_INBOUND"

PERIODS = ("day", "week", "month", "year")

# Rule kind -> {param: type}. Types: "amount", "int", "str", "list", "bool", "period", "evidence_kind".
# Params ending in "?" are optional.
RULE_PARAMS = {
    "allowed_payees": {"payee_ids": "list"},
    "allowed_beneficiaries": {"beneficiary_ids": "list"},
    "allowed_products": {"products": "list"},
    "max_per_request": {"amount": "amount"},
    "cap_per_period": {"amount": "amount", "period": "period", "product?": "str", "shared?": "bool"},
    "min_interval": {"hours": "int", "product?": "str"},
    "requires_evidence": {"kind": "evidence_kind", "label?": "str"},
    "price_ceiling": {"item": "str", "max_unit_price": "amount", "keywords?": "list"},
    "requires_invoice": {},
    "escalate_above": {"amount": "amount"},
    "auto_approve_below": {"amount": "amount"},
}

# Rules that never refuse; when triggered they send the request to a funder.
SOFT_RULES = frozenset({"escalate_above", "auto_approve_below"})


@dataclass(frozen=True)
class MandateTemplate:
    type: str
    label: str
    purpose: str
    priority: str  # MUST / SHOULD / COULD
    required_rules: tuple
    default_rules: tuple = ()  # ({"kind", "params"}, ...) suggested starting point for drafting
    payee_kinds: tuple = ()
    funding: tuple = (PAYPAL_CHECKOUT,)
    products: tuple = field(default_factory=tuple)


TEMPLATES = {
    t.type: t
    for t in (
        MandateTemplate(
            type=Mandate.AKHA,
            label="Akha (Build)",
            purpose="Check quotes against a price ceiling and milestone photos, then pay the supplier directly",
            priority="MUST",
            required_rules=("allowed_payees", "max_per_request", "requires_evidence"),
            default_rules=(
                {"kind": "requires_evidence", "params": {"kind": Evidence.MILESTONE_PHOTO, "label": ""}},
            ),
            payee_kinds=(Payee.SUPPLIER,),
        ),
        MandateTemplate(
            type=Mandate.IMFUNDO,
            label="Imfundo (School fees)",
            purpose="Fees locked to a named school, paid on the school's invoice",
            priority="MUST",
            required_rules=("allowed_payees", "requires_invoice"),
            default_rules=({"kind": "requires_invoice", "params": {}},),
            payee_kinds=(Payee.SCHOOL,),
        ),
        MandateTemplate(
            type=Mandate.ISIKHWAMA,
            label="Isikhwama (Shared support)",
            purpose="Several funders share caps for airtime, bundles and cash for a registered beneficiary",
            priority="MUST",
            required_rules=("allowed_beneficiaries", "allowed_products"),
            default_rules=(
                {"kind": "allowed_products", "params": {"products": ["airtime", "bundles", "cash"]}},
            ),
            payee_kinds=(Payee.MOBILE_MONEY_PROVIDER,),
            products=("airtime", "bundles", "cash"),
        ),
        MandateTemplate(
            type=Mandate.ISILILO,
            label="Isililo (Funeral)",
            purpose="A funeral pool that pays funeral providers on invoice; optional funeral cover premiums",
            priority="SHOULD",
            required_rules=("allowed_payees", "requires_invoice"),
            default_rules=({"kind": "requires_invoice", "params": {}},),
            payee_kinds=(Payee.FUNERAL_PROVIDER,),
            funding=(PAYPAL_CHECKOUT, PAYPAL_SUBSCRIPTIONS, PAYNOW_INBOUND),
        ),
        MandateTemplate(
            type=Mandate.VIKELA,
            label="Vikela (Health)",
            purpose="Local medical aid premiums paid to the medical aid",
            priority="COULD",
            required_rules=("allowed_payees", "max_per_request"),
            payee_kinds=(Payee.MEDICAL_AID,),
            funding=(PAYPAL_SUBSCRIPTIONS, PAYPAL_CHECKOUT),
        ),
    )
}


def get_template(mandate_type):
    try:
        return TEMPLATES[mandate_type]
    except KeyError:
        raise ValueError(f"Unknown mandate type: {mandate_type}")


def _check_param(kind, name, expected, value):
    if expected == "amount":
        try:
            ok = Decimal(str(value)) > 0
        except (InvalidOperation, ValueError):
            ok = False
        return None if ok else f"{kind}.{name} must be a positive amount"
    if expected == "int":
        return None if isinstance(value, int) and not isinstance(value, bool) and value > 0 \
            else f"{kind}.{name} must be a positive whole number"
    if expected == "str":
        return None if isinstance(value, str) else f"{kind}.{name} must be text"
    if expected == "list":
        return None if isinstance(value, list) and value else f"{kind}.{name} must be a non-empty list"
    if expected == "bool":
        return None if isinstance(value, bool) else f"{kind}.{name} must be true or false"
    if expected == "period":
        return None if value in PERIODS else f"{kind}.{name} must be one of {', '.join(PERIODS)}"
    if expected == "evidence_kind":
        kinds = [k for k, _ in Evidence.KINDS]
        return None if value in kinds else f"{kind}.{name} must be one of {', '.join(kinds)}"
    return f"{kind}.{name}: unknown param type {expected}"


def validate_rule(rule):
    """Errors for one {"kind", "params"} dict (empty list = valid)."""
    kind = rule.get("kind")
    params = rule.get("params") or {}
    if kind not in RULE_PARAMS:
        return [f"Unknown rule kind: {kind}"]
    if not isinstance(params, dict):
        return [f"{kind}: params must be an object"]
    spec = RULE_PARAMS[kind]
    allowed = {name.rstrip("?") for name in spec}
    errors = [f"{kind}: unknown param {name}" for name in params if name not in allowed]
    for name, expected in spec.items():
        key = name.rstrip("?")
        if key not in params:
            if not name.endswith("?"):
                errors.append(f"{kind}: missing param {key}")
            continue
        if error := _check_param(kind, key, expected, params[key]):
            errors.append(error)
    return errors


def validate_rules(mandate_type, rules):
    """Errors for a full rule set against its template (empty list = valid)."""
    template = get_template(mandate_type)
    errors = []
    for rule in rules:
        errors.extend(validate_rule(rule))
    kinds = {rule.get("kind") for rule in rules}
    errors.extend(f"{template.label} mandates need a {kind} rule"
                  for kind in template.required_rules if kind not in kinds)
    return errors
