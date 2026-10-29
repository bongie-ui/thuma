"""REST API for families' mandates, requests, people and the ledger (BUILD_SPEC §10).

Views only translate HTTP to services; every state change goes through mandates.services.
"""

import uuid

from django.db.models import Q
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from agent import drafting
from agent.llm import LLMError
from core.api import IsFamilyMember, current_family, current_membership, get_or_404
from core.phones import normalize_phone
from payments import payouts, rails

from . import services
from .describe import coverage, describe_rule
from .models import Approval, Evidence, LedgerEntry, Mandate, Payee, Request, Upload
from .serializers import (BeneficiarySerializer, LedgerEntrySerializer, MandateSerializer, MemberSerializer,
                          PayeeSerializer, RequestDetailSerializer, RequestSerializer, display_name)
from .templates import TEMPLATES, validate_rules

PERMS = [IsFamilyMember]
EVIDENCE_KINDS = {k for k, _ in Evidence.KINDS}


def _require(data, *names):
    missing = [n for n in names if data.get(n) in (None, "")]
    if missing:
        raise ValidationError({n: "This field is required." for n in missing})


def _family_user(family, user_id):
    m = family.memberships.select_related("user").filter(user_id=user_id).first()
    if m is None:
        raise ValidationError({"user_id": "Not a member of this family"})
    return m.user


# --- Beneficiaries and payees -----------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes(PERMS)
def beneficiaries(request):
    family = current_family(request)
    if request.method == "GET":
        return Response(BeneficiarySerializer(family.beneficiaries.order_by("name"), many=True).data)
    _require(request.data, "name", "phone")
    b = services.register_beneficiary(family=family, name=request.data["name"], phone=request.data["phone"],
                                      registered_by=request.user,
                                      relationship=request.data.get("relationship", ""),
                                      allowed_products=request.data.get("allowed_products") or [])
    return Response(BeneficiarySerializer(b).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes(PERMS)
def beneficiary_detail(request, pk):
    family = current_family(request)
    b = get_or_404(family.beneficiaries, pk=pk)
    services.require_funder(request.user, family)
    data = request.data
    if "phone" in data:
        services.change_beneficiary_phone(b, data["phone"], request.user)
    fields = [f for f in ("name", "relationship", "allowed_products") if f in data]
    for f in fields:
        setattr(b, f, data[f])
    if fields:
        b.save(update_fields=[*fields, "updated_at"])
    return Response(BeneficiarySerializer(b).data)


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def payees(request):
    family = current_family(request)
    if request.method == "GET":
        qs = Payee.objects.filter(Q(family=family) | Q(family__isnull=True)).order_by("name")
        return Response(PayeeSerializer(qs, many=True).data)
    services.require_funder(request.user, family)
    data = request.data.copy()
    if data.get("phone"):
        data["phone"] = normalize_phone(data["phone"]) or data["phone"]  # invalid numbers fail validation
    serializer = PayeeSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    # New payees start unverified; verification is an admin step.
    payee = serializer.save(family=family, verified=False)
    return Response(PayeeSerializer(payee).data, status=status.HTTP_201_CREATED)


# --- Mandates ---------------------------------------------------------------------------------------------

def _mandates(family):
    return family.mandates.prefetch_related("rules", "mandate_funders__user")


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_types(request):
    return Response([{"type": t.type, "label": t.label, "purpose": t.purpose, "priority": t.priority,
                      "required_rules": t.required_rules} for t in TEMPLATES.values()])


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def mandates(request):
    family = current_family(request)
    if request.method == "GET":
        qs = _mandates(family).exclude(status=Mandate.CLOSED).order_by("created_at")
        return Response(MandateSerializer(qs, many=True).data)
    data = request.data
    _require(data, "type", "title", "rules")
    if data["type"] not in TEMPLATES:
        raise ValidationError({"type": "Unknown mandate type"})
    co_funders = [_family_user(family, uid) for uid in data.get("co_funder_ids", []) if uid != request.user.id]
    mandate = services.create_mandate(family=family, type=data["type"], title=data["title"], rules=data["rules"],
                                      created_by=request.user, purpose_text=data.get("purpose_text", ""),
                                      co_funders=co_funders)
    return Response(MandateSerializer(mandate).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes(PERMS)
def mandate_draft(request):
    """Plain language -> a proposed mandate for the funder to check. Nothing is saved or signed here."""
    family = current_family(request)
    services.require_funder(request.user, family)
    _require(request.data, "text")
    try:
        draft = drafting.draft_mandate(request.data["text"], family)
    except LLMError as exc:
        return Response({"detail": f"The assistant could not draft this right now: {exc}"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    draft["rules"] = [{**r, "text": describe_rule(r["kind"], r.get("params"))} for r in draft["rules"]]
    return Response(draft)


@api_view(["POST"])
@permission_classes(PERMS)
def rules_preview(request):
    """Validate an edited rule set and describe it, before the funder confirms and signs."""
    _require(request.data, "type")
    rules = request.data.get("rules") or []
    if request.data["type"] not in TEMPLATES:
        raise ValidationError({"type": "Unknown mandate type"})
    return Response({"errors": validate_rules(request.data["type"], rules),
                     "rules": [{**r, "text": describe_rule(r.get("kind"), r.get("params"))} for r in rules]})


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_detail(request, pk):
    return Response(MandateSerializer(get_or_404(_mandates(current_family(request)), pk=pk)).data)


@api_view(["POST"])
@permission_classes(PERMS)
def mandate_funders(request, pk):
    family = current_family(request)
    mandate = get_or_404(family.mandates, pk=pk)
    if not services.is_owner(mandate, request.user):
        raise ValidationError({"detail": "Only the mandate owner can add funders"})
    _require(request.data, "user_id")
    services.add_funder(mandate, _family_user(family, request.data["user_id"]), added_by=request.user)
    return Response(MandateSerializer(mandate).data)


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_coverage(request, pk):
    """What each product has used this period, and who covered it (Isikhwama quick actions)."""
    family = current_family(request)
    mandate = get_or_404(family.mandates.prefetch_related("rules"), pk=pk)
    beneficiary = get_or_404(family.beneficiaries, pk=request.query_params.get("beneficiary"))
    return Response(coverage(mandate, beneficiary))


# --- Requests ---------------------------------------------------------------------------------------------

def _requests(family):
    return Request.objects.filter(mandate__family=family) \
        .select_related("mandate", "beneficiary", "payee", "requester_user", "risk_assessment")


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def requests_(request):
    family = current_family(request)
    if request.method == "GET":
        if request.query_params.get("inbox"):
            qs = services.inbox(request.user).select_related("requester_user", "risk_assessment")
        else:
            qs = _requests(family).order_by("-created_at")
            if s := request.query_params.get("status"):
                qs = qs.filter(status__in=s.split(","))
            if m := request.query_params.get("mandate"):
                qs = qs.filter(mandate_id=m)
        return Response(RequestSerializer(qs[:100], many=True).data)

    data = request.data
    _require(data, "mandate", "amount", "product")
    mandate = get_or_404(family.mandates, pk=data["mandate"])
    beneficiary = get_or_404(family.beneficiaries, pk=data["beneficiary"]) if data.get("beneficiary") else None
    payee = (get_or_404(Payee.objects.filter(Q(family=family) | Q(family__isnull=True)), pk=data["payee"])
             if data.get("payee") else services.sole_payee(mandate))
    uploads = []
    for item in data.get("uploads") or []:
        if item.get("kind") not in EVIDENCE_KINDS:
            raise ValidationError({"uploads": f"Unknown evidence kind {item.get('kind')}"})
        uploads.append((get_or_404(family.uploads, pk=item.get("upload_id")), item["kind"]))
    req = services.submit_request(
        mandate=mandate, amount=data["amount"], product=data["product"], beneficiary=beneficiary, payee=payee,
        channel=Request.APP, requester_user=request.user, requester_display=display_name(request.user),
        message_text=data.get("message_text", ""), uploads=uploads,
        idempotency_key=f"app-{data.get('idempotency_key') or uuid.uuid4()}")
    return Response(RequestDetailSerializer(req).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes(PERMS)
def request_detail(request, pk):
    req = get_or_404(_requests(current_family(request)).prefetch_related("evidence__upload", "decisions",
                                                                         "approvals__user"), pk=pk)
    tx = req.rail_transactions.order_by("-created_at").first()
    if tx is not None:
        try:
            payouts.refresh(tx)  # no webhooks locally; cheap when nothing is pending
        except rails.RailError:
            pass
        req.refresh_from_db()
    return Response(RequestDetailSerializer(req).data)


@api_view(["POST"])
@permission_classes(PERMS)
def request_approval(request, pk):
    req = get_or_404(_requests(current_family(request)), pk=pk)
    action = request.data.get("action")
    if action not in {a for a, _ in Approval.ACTIONS}:
        raise ValidationError({"action": "Choose APPROVE, REJECT, VERIFIED_SAFE or REPORT_FRAUD"})
    req = services.apply_approval(req, request.user, action, note=request.data.get("note", ""))
    return Response(RequestDetailSerializer(req).data)


# --- Uploads ----------------------------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes(PERMS)
@parser_classes([MultiPartParser])
def uploads(request):
    f = request.FILES.get("file")
    if f is None:
        raise ValidationError({"file": "Attach a file"})
    upload = services.create_upload(family=current_family(request), data=f.read(), content_type=f.content_type,
                                    name=f.name, user=request.user)
    return Response({"id": str(upload.id), "name": upload.name, "content_type": upload.content_type,
                     "size": upload.size}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes(PERMS)
def upload_file(request, pk):
    upload = get_or_404(Upload.objects.filter(family=current_family(request)), pk=pk)
    response = HttpResponse(bytes(upload.data), content_type=upload.content_type)
    response["Content-Disposition"] = f'inline; filename="{upload.name or upload.id}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- Ledger and family ------------------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes(PERMS)
def ledger(request):
    family = current_family(request)
    qs = LedgerEntry.objects.filter(family=family).select_related("mandate").order_by("-created_at")
    if m := request.query_params.get("mandate"):
        qs = qs.filter(mandate_id=m)
    if r := request.query_params.get("request"):
        qs = qs.filter(request_id=r)
    names = {m.user_id: display_name(m.user) for m in family.memberships.select_related("user")}
    return Response(LedgerEntrySerializer(qs[:200], many=True, context={"user_names": names}).data)


@api_view(["GET"])
@permission_classes(PERMS)
def family(request):
    m = current_membership(request)
    members = m.family.memberships.select_related("user").order_by("created_at")
    return Response({"id": str(m.family.id), "name": m.family.name, "role": m.role,
                     "members": MemberSerializer(members, many=True).data})
