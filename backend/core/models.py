import uuid

from django.db import models


class BaseModel(models.Model):
    """UUID primary key + timestamps, shared by every Thuma model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["created_at"]


def money_field(**kwargs):
    return models.DecimalField(max_digits=12, decimal_places=2, **kwargs)


def currency_field(**kwargs):
    return models.CharField(max_length=3, default="USD", **kwargs)
