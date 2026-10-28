"""Plain-language purpose -> proposed mandate (BUILD_SPEC §9).

The draft is only a proposal: the funder reviews it and services.create_mandate validates and signs it.
"""

import json

from mandates.models import Beneficiary, Mandate, Payee
from mandates.templates import RULE_PARAMS, TEMPLATES, validate_rules

from . import llm, prompts

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["type", "title", "rules", "explanation", "questions"],
    "properties": {
        "type": {"type": "string", "enum": list(TEMPLATES)},
        "title": {"type": "string"},
        "rules": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "params_json"],
            "properties": {"kind": {"type": "string", "enum": list(RULE_PARAMS)},
                           "params_json": {"type": "string"}}}},
        "explanation": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
}

ID_PARAMS = {"allowed_payees": "payee_ids", "allowed_beneficiaries": "beneficiary_ids"}


def _types():
    return "\n".join(f"- {t.type}: {t.label}. {t.purpose}. Requires: {', '.join(t.required_rules)}"
                     for t in TEMPLATES.values())


def _rule_kinds():
    return "\n".join(f"- {kind}: {json.dumps(spec)}" for kind, spec in RULE_PARAMS.items())


def _payees(family):
    payees = Payee.objects.filter(family=family) | Payee.objects.filter(family__isnull=True)
    return "\n".join(f"- {p.id}: {p.name} ({p.get_kind_display()})" for p in payees) or "(none registered)"


def _beneficiaries(family):
    return "\n".join(f"- {b.id}: {b.name} ({b.relationship or 'family'}; products: "
                     f"{', '.join(b.allowed_products) or 'none'})"
                     for b in Beneficiary.objects.filter(family=family)) or "(none registered)"


def _parse(raw, family):
    """Model output -> {type, title, rules, explanation, questions}, keeping only this family's ids."""
    valid_ids = {
        "payee_ids": {str(p) for p in (Payee.objects.filter(family=family) | Payee.objects.filter(family__isnull=True))
                      .values_list("id", flat=True)},
        "beneficiary_ids": {str(b) for b in Beneficiary.objects.filter(family=family).values_list("id", flat=True)},
    }
    questions = list(raw.get("questions") or [])
    rules = []
    for item in raw.get("rules") or []:
        try:
            params = json.loads(item.get("params_json") or "{}")
        except ValueError:
            params = None
        if not isinstance(params, dict):
            questions.append(f"Could not read the settings for the {item.get('kind')} rule")
            continue
        if (param := ID_PARAMS.get(item.get("kind"))) and isinstance(params.get(param), list):
            unknown = [i for i in params[param] if str(i) not in valid_ids[param]]
            params[param] = [str(i) for i in params[param] if str(i) in valid_ids[param]]
            if unknown:
                questions.append("Some payees or beneficiaries mentioned are not registered yet")
        rules.append({"kind": item.get("kind"), "params": params})
    return {"type": raw.get("type"), "title": raw.get("title", ""), "rules": rules,
            "explanation": raw.get("explanation", ""), "questions": questions}


def draft_mandate(text, family, currency="USD"):
    """Returns {type, title, rules, explanation, questions, errors, model}. `errors` empty = ready to sign."""
    repair = ""
    draft, model = None, ""
    for _attempt in range(2):
        prompt = prompts.render("drafting", types=_types(), rule_kinds=_rule_kinds(), payees=_payees(family),
                                beneficiaries=_beneficiaries(family), text=text, currency=currency, repair=repair)
        raw, model = llm.structured(prompt, SCHEMA, name="mandate_draft")
        draft = _parse(raw, family)
        errors = validate_rules(draft["type"], draft["rules"]) if draft["type"] in TEMPLATES else \
            [f"Unknown mandate type {draft['type']}"]
        if not errors:
            break
        repair = ("Your previous draft had these problems; fix them and return the full draft again:\n- "
                  + "\n- ".join(errors))
    draft["errors"] = errors
    draft["model"] = model
    draft["purpose_text"] = text
    draft["type_label"] = dict(Mandate.TYPES).get(draft["type"], draft["type"])
    return draft
