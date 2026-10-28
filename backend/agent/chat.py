"""The conversation agent (BUILD_SPEC §9).

Participants are funders (users) or people identified by phone: a registered beneficiary, a registered
payee, or an unknown number. Tools can create requests and attach evidence; NO tool can pay, approve,
change rules or change beneficiaries. Requests go through fraud.assess -> policy -> execute_decision.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.phones import normalize_phone
from mandates import services
from mandates.models import Beneficiary, Evidence, Mandate, MandateFunder, Payee, Request, Upload
from mandates.templates import TEMPLATES

from . import llm, prompts
from .models import ChatMessage

MAX_TOOL_ROUNDS = 6
HISTORY_MESSAGES = 20
NULLABLE_STR = {"type": ["string", "null"]}


def _tool(name, description, properties=None):
    properties = properties or {}
    return {"type": "function", "function": {
        "name": name, "description": description, "strict": True,
        "parameters": {"type": "object", "additionalProperties": False, "properties": properties,
                       "required": list(properties)}}}


TOOLS = [
    _tool("get_mandates", "List the mandates this person can use, with their rules (and balances for funders)."),
    _tool("get_beneficiaries", "List the beneficiaries this person can make requests for."),
    _tool("create_request", "Create a payment request. This does not pay: the rules engine decides.", {
        "mandate_id": {"type": "string"},
        "product": {"type": "string", "description": "e.g. airtime, bundles, cash, materials, school_fees"},
        "amount": {"type": "number"},
        "payee_id": NULLABLE_STR,
        "beneficiary_id": NULLABLE_STR,
        "summary_en": {"type": "string", "description": "One-sentence English summary of what is asked"},
        "attachments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["upload_id", "kind"],
            "properties": {"upload_id": {"type": "string"},
                           "kind": {"type": "string", "enum": [k for k, _ in Evidence.KINDS]}}}},
    }),
    _tool("attach_evidence", "Attach an uploaded file to an existing request and re-check it.", {
        "request_id": {"type": "string"},
        "upload_id": {"type": "string"},
        "kind": {"type": "string", "enum": [k for k, _ in Evidence.KINDS]},
    }),
    _tool("get_request_status", "Current status of a request.", {"request_id": {"type": "string"}}),
    _tool("explain_decision", "Rule results (and, for funders, risk flags) behind a request's decision.",
          {"request_id": {"type": "string"}}),
]

TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)


class ToolError(Exception):
    pass


@dataclass
class Participant:
    family: object
    user: object = None
    phone: str = ""
    beneficiary: object = None
    payee: object = None

    @classmethod
    def for_conversation(cls, conversation):
        if conversation.participant_user_id:
            return cls(family=conversation.family, user=conversation.participant_user)
        phone = normalize_phone(conversation.participant_phone) or conversation.participant_phone
        return cls(family=conversation.family, phone=phone,
                   beneficiary=Beneficiary.objects.filter(family=conversation.family, phone=phone).first(),
                   payee=(Payee.objects.filter(family=conversation.family, phone=phone).first()
                          or Payee.objects.filter(family__isnull=True, phone=phone).first()))

    @property
    def is_funder(self):
        return self.user is not None

    @property
    def description(self):
        if self.is_funder:
            return "a funder of this family, who sends and oversees money for relatives at home"
        if self.beneficiary:
            return "a beneficiary the family supports, who can ask for what their mandates allow"
        if self.payee:
            return "a payee (supplier, school or provider) sending quotes, invoices and progress photos"
        return "someone writing from a number the family has not registered"


def _rule_ids(mandate, kind, param):
    return {str(i) for r in mandate.rules.all() if r.kind == kind for i in r.params.get(param, [])}


def visible_mandates(p):
    active = Mandate.objects.filter(family=p.family, status=Mandate.ACTIVE).prefetch_related("rules")
    if p.is_funder:
        return [m for m in active.filter(mandate_funders__user=p.user)]
    if p.beneficiary:
        return [m for m in active if str(p.beneficiary.id) in _rule_ids(m, "allowed_beneficiaries",
                                                                        "beneficiary_ids")]
    if p.payee:
        return [m for m in active if str(p.payee.id) in _rule_ids(m, "allowed_payees", "payee_ids")]
    # Unknown numbers may still ask for support for a family member; fraud checks decide the risk.
    return [m for m in active if _rule_ids(m, "allowed_beneficiaries", "beneficiary_ids")]


def _visible_request(p, request_id):
    try:
        request = Request.objects.select_related("mandate").get(pk=request_id, mandate__family=p.family)
    except (Request.DoesNotExist, ValueError, ValidationError):
        raise ToolError("No such request")
    if p.is_funder and MandateFunder.objects.filter(mandate=request.mandate, user=p.user).exists():
        return request
    if not p.is_funder and request.requester_phone == p.phone:
        return request
    raise ToolError("No such request")


def _upload(p, upload_id):
    try:
        return Upload.objects.get(pk=upload_id, family=p.family)
    except (Upload.DoesNotExist, ValueError, ValidationError):
        raise ToolError(f"No such upload {upload_id}")


def outcome(p, request):
    request.refresh_from_db()
    decision = request.latest_decision
    data = {"request_id": str(request.id), "status": request.status, "amount": str(request.amount),
            "product": request.product}
    if request.status == Request.HELD_FRAUD and not p.is_funder:
        data["message"] = "Held until the family confirms it with the beneficiary on their registered number"
        return data
    if decision:
        data["decision"] = decision.outcome
        data["reason"] = decision.reason
        data["failed_rules"] = [r["detail"] for r in decision.rule_results if not r["passed"]]
    tx = request.rail_transactions.order_by("-created_at").first()
    if tx:
        data["payment"] = {"status": tx.status, "delivery": tx.last_mile_status, "simulated_rail": tx.simulated}
        if tx.collection_code and (p.is_funder or p.beneficiary):
            data["payment"]["collection_code"] = tx.collection_code
    return data


# --- Tools ------------------------------------------------------------------------------------------------

def _rule_text(rule):
    return {"kind": rule.kind, "params": rule.params}


def tool_get_mandates(p, conversation, current):
    result = []
    for m in visible_mandates(p):
        item = {"mandate_id": str(m.id), "type": TEMPLATES[m.type].label}
        if p.is_funder or p.beneficiary or p.payee:
            item.update(title=m.title, rules=[_rule_text(r) for r in m.rules.all()])
        if p.is_funder:
            item["balance"] = str(services.mandate_balance(m))
            item["currency"] = m.currency
        result.append(item)
    return result


def tool_get_beneficiaries(p, conversation, current):
    if p.beneficiary:
        qs = [p.beneficiary]
    elif p.payee:
        qs = []
    else:
        qs = Beneficiary.objects.filter(family=p.family)
    return [{"beneficiary_id": str(b.id), "name": b.name,
             **({"relationship": b.relationship, "allowed_products": b.allowed_products} if p.is_funder else {})}
            for b in qs]


def tool_create_request(p, conversation, current, mandate_id, product, amount, payee_id, beneficiary_id,
                        summary_en, attachments):
    mandate = next((m for m in visible_mandates(p) if str(m.id) == mandate_id), None)
    if mandate is None:
        raise ToolError("No such mandate")
    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ToolError("Invalid amount")

    beneficiary = p.beneficiary
    if beneficiary is None and beneficiary_id:
        beneficiary = Beneficiary.objects.filter(pk=beneficiary_id, family=p.family).first()
    payee = p.payee
    if payee is None and payee_id:
        payee = (Payee.objects.filter(pk=payee_id, family=p.family).first()
                 or Payee.objects.filter(pk=payee_id, family__isnull=True).first())
    if payee is None:
        allowed = _rule_ids(mandate, "allowed_payees", "payee_ids")
        if len(allowed) == 1:  # e.g. the single mobile money provider of a support mandate
            payee = Payee.objects.filter(pk=next(iter(allowed))).first()
    uploads = [(_upload(p, a["upload_id"]), a["kind"]) for a in attachments]

    request = services.submit_request(
        mandate=mandate, amount=amount, product=product, payee=payee, beneficiary=beneficiary,
        channel=Request.CHAT, requester_user=p.user,
        requester_phone="" if p.is_funder else p.phone,
        requester_display=(p.user.get_full_name() or p.user.username) if p.is_funder else
        (p.beneficiary.name if p.beneficiary else p.payee.name if p.payee else p.phone),
        # The fraud check must see the person's own words, never the model's paraphrase.
        message_text=current.text, summary_en=summary_en,
        idempotency_key=f"chat-{current.id}-{mandate.id}-{product}-{amount}", uploads=uploads)
    current.linked_request = request
    current.save(update_fields=["linked_request", "updated_at"])
    return outcome(p, request)


def tool_attach_evidence(p, conversation, current, request_id, upload_id, kind):
    request = _visible_request(p, request_id)
    evidence = services.attach_evidence(request, _upload(p, upload_id), kind)
    if request.status in (Request.NEW, Request.ASSESSED, Request.REFUSED):
        services.reassess(request)
    data = outcome(p, request)
    if getattr(evidence, "error", ""):
        data["evidence_problem"] = evidence.error
    return data


def tool_get_request_status(p, conversation, current, request_id):
    return outcome(p, _visible_request(p, request_id))


def tool_explain_decision(p, conversation, current, request_id):
    request = _visible_request(p, request_id)
    data = outcome(p, request)
    decision = request.latest_decision
    if decision and not (request.status == Request.HELD_FRAUD and not p.is_funder):
        data["rule_results"] = [{"kind": r["kind"], "passed": r["passed"], "detail": r["detail"]}
                                for r in decision.rule_results]
    if p.is_funder and hasattr(request, "risk_assessment"):
        risk = request.risk_assessment
        data["risk"] = {"level": risk.level, "score": risk.score, "signals": [s["detail"] for s in risk.signals],
                        "flags": risk.ai_flags, "summary": risk.ai_summary,
                        "verification": risk.suggested_verification}
    return data


_EXECUTORS = {
    "get_mandates": tool_get_mandates,
    "get_beneficiaries": tool_get_beneficiaries,
    "create_request": tool_create_request,
    "attach_evidence": tool_attach_evidence,
    "get_request_status": tool_get_request_status,
    "explain_decision": tool_explain_decision,
}
assert set(_EXECUTORS) == TOOL_NAMES


def run_tool(p, conversation, current, name, arguments):
    if name not in _EXECUTORS:
        return {"error": f"Unknown tool {name}"}
    try:
        args = json.loads(arguments or "{}")
        return _EXECUTORS[name](p, conversation, current, **args)
    except (ToolError, services.ServiceError) as exc:
        return {"error": str(exc)}
    except (TypeError, ValueError) as exc:
        return {"error": f"Bad arguments: {exc}"}


# --- Turn loop --------------------------------------------------------------------------------------------

def _history(conversation, current):
    messages = []
    for m in conversation.messages.exclude(pk=current.pk).order_by("-created_at")[:HISTORY_MESSAGES][::-1]:
        if m.role in ("user", "assistant") and m.text:
            messages.append({"role": m.role, "content": m.text})
    return messages


def _current_content(current):
    uploads = Upload.objects.filter(pk__in=[a["upload_id"] for a in current.attachments])
    text = current.text or ""
    if uploads:
        text += "\n" + "\n".join(f"[attached file upload_id={u.id} name={u.name or 'file'}]" for u in uploads)
    return llm.user_content(text, [(bytes(u.data), u.content_type) for u in uploads if u.is_image])


def run_turn(conversation, text, uploads=(), llm_chat=None):
    """Handle one user message; returns the saved assistant ChatMessage."""
    llm_chat = llm_chat or llm.chat
    p = Participant.for_conversation(conversation)
    current = ChatMessage.objects.create(conversation=conversation, role="user", text=text,
                                         attachments=[{"upload_id": str(u.id), "name": u.name,
                                                       "content_type": u.content_type} for u in uploads])
    system = prompts.render("chat_system", participant_description=p.description,
                            today=timezone.localdate().isoformat())
    messages = [{"role": "system", "content": system}, *_history(conversation, current),
                {"role": "user", "content": _current_content(current)}]
    reply = ""
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            response = llm_chat(messages, TOOLS)
            if not response["tool_calls"]:
                reply = response["content"]
                break
            messages.append({"role": "assistant", "content": response["content"] or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in response["tool_calls"]]})
            for call in response["tool_calls"]:
                result = run_tool(p, conversation, current, call["name"], call["arguments"])
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
        else:
            reply = "Sorry, I could not finish that. Please try again."
    except llm.LLMError:
        reply = "Sorry, the assistant is unavailable right now. Please try again in a moment."
    current.refresh_from_db()
    return ChatMessage.objects.create(conversation=conversation, role="assistant", text=reply,
                                      linked_request=current.linked_request)
