from django.conf import settings
from django.db import models

from accounts.models import Family
from core.models import BaseModel


class Conversation(BaseModel):
    """A chat thread with a funder (user) or a beneficiary/payee (identified by phone)."""

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="conversations")
    participant_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.CASCADE, related_name="conversations")
    participant_phone = models.CharField(max_length=16, blank=True)
    title = models.CharField(max_length=120, blank=True)


class ChatMessage(BaseModel):
    ROLES = [("user", "User"), ("assistant", "Assistant"), ("system", "System")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLES)
    text = models.TextField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    linked_request = models.ForeignKey("mandates.Request", null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="chat_messages")
