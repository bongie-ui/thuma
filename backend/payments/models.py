from django.db import models

from core.models import BaseModel, money_field


class RailTransaction(BaseModel):
    """One attempt to move money for a Request on a rail (real or simulated)."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETURNED = "RETURNED"
    STATUSES = [(s, s.title()) for s in (PENDING, SUCCESS, FAILED, RETURNED)]

    LAST_MILE_NA = "N/A"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    AWAITING_COLLECTION = "AWAITING_COLLECTION"
    COLLECTED = "COLLECTED"
    LAST_MILE_STATUSES = [(s, s.replace("_", " ").title()) for s in
                          (LAST_MILE_NA, DELIVERING, DELIVERED, AWAITING_COLLECTION, COLLECTED)]

    request = models.ForeignKey("mandates.Request", on_delete=models.PROTECT, related_name="rail_transactions")
    rail = models.CharField(max_length=20)  # Payee.rail value
    amount = money_field()
    reference = models.CharField(max_length=64)  # thuma-<request id>; PayPal sender_batch_id
    external_id = models.CharField(max_length=64, blank=True)  # payout batch / item id
    simulated = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    last_mile_status = models.CharField(max_length=20, choices=LAST_MILE_STATUSES, default=LAST_MILE_NA)
    collection_code = models.CharField(max_length=6, blank=True)
    raw = models.JSONField(default=dict, blank=True)


class WebhookEvent(BaseModel):
    paypal_event_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
