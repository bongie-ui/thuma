from django.contrib import admin

from .models import RailTransaction, WebhookEvent


@admin.register(RailTransaction)
class RailTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "rail", "amount", "status", "last_mile_status", "simulated", "created_at")
    list_filter = ("rail", "status", "simulated")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("paypal_event_id", "event_type", "processed_at", "created_at")
    list_filter = ("event_type",)
