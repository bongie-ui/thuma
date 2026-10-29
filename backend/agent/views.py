"""Chat API. A funder talks to the agent as themselves. In DEMO_MODE a funder can also play a phone number
(a beneficiary, a payee or an unknown sender) to show what those people see; the agent treats that
conversation exactly as it would a message from that number."""

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from core.api import IsFamilyMember, current_family, get_or_404
from core.phones import normalize_phone
from mandates.models import Beneficiary, Payee

from . import chat
from .models import ChatMessage, Conversation

PERMS = [IsFamilyMember]


def _label(conversation):
    if conversation.participant_user_id:
        return "You"
    phone = conversation.participant_phone
    family = conversation.family
    if b := Beneficiary.objects.filter(family=family, phone=phone).first():
        return f"{b.name} (beneficiary)"
    if p := (Payee.objects.filter(family=family, phone=phone).first()
             or Payee.objects.filter(family__isnull=True, phone=phone).first()):
        return f"{p.name} (payee)"
    return f"{phone} (unregistered number)"


def _conversation_data(c):
    return {"id": str(c.id), "phone": c.participant_phone or None, "is_me": bool(c.participant_user_id),
            "label": _label(c), "updated_at": c.updated_at}


def _message_data(m, participant):
    return {"id": str(m.id), "role": m.role, "text": m.text, "attachments": m.attachments,
            "created_at": m.created_at,
            # Scoped like the agent's own view: a requester never sees fraud details.
            "card": chat.outcome(participant, m.linked_request) if m.linked_request_id else None}


def _visible(request):
    family = current_family(request)
    qs = Conversation.objects.filter(family=family)
    if settings.DEMO_MODE:
        return qs.filter(participant_user=request.user) | qs.filter(participant_user__isnull=True)
    return qs.filter(participant_user=request.user)


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def conversations(request):
    family = current_family(request)
    if request.method == "GET":
        return Response([_conversation_data(c) for c in _visible(request).order_by("-updated_at")])
    raw = (request.data.get("phone") or "").strip()
    if not raw:
        c, _ = Conversation.objects.get_or_create(family=family, participant_user=request.user,
                                                  defaults={"title": "Funder chat"})
        return Response(_conversation_data(c))
    if not settings.DEMO_MODE:
        raise NotFound()
    phone = normalize_phone(raw)
    if not phone:
        raise ValidationError({"phone": "Enter a valid phone number"})
    c, _ = Conversation.objects.get_or_create(family=family, participant_phone=phone, participant_user=None)
    return Response(_conversation_data(c), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def messages(request, pk):
    conversation = get_or_404(_visible(request), pk=pk)
    participant = chat.Participant.for_conversation(conversation)
    if request.method == "POST":
        text = (request.data.get("text") or "").strip()
        uploads = [get_or_404(conversation.family.uploads, pk=uid) for uid in request.data.get("upload_ids") or []]
        if not text and not uploads:
            raise ValidationError({"text": "Write a message or attach a photo"})
        chat.run_turn(conversation, text, uploads=uploads)
        conversation.save(update_fields=["updated_at"])
    qs = ChatMessage.objects.filter(conversation=conversation).exclude(role="system") \
        .select_related("linked_request").order_by("created_at")
    return Response({"conversation": _conversation_data(conversation),
                     "messages": [_message_data(m, participant) for m in qs]})
