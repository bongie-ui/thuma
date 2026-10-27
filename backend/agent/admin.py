from django.contrib import admin

from .models import ChatMessage, Conversation


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("family", "participant_user", "participant_phone", "created_at")
    inlines = [ChatMessageInline]
