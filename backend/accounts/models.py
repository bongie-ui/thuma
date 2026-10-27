from django.conf import settings
from django.db import models

from core.models import BaseModel
from core.phones import validate_e164


class Family(BaseModel):
    name = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="families_created")

    class Meta(BaseModel.Meta):
        verbose_name_plural = "families"

    def __str__(self):
        return self.name


class Membership(BaseModel):
    ADMIN = "ADMIN"
    FUNDER = "FUNDER"
    VIEWER = "VIEWER"
    ROLES = [(ADMIN, "Admin"), (FUNDER, "Funder"), (VIEWER, "Viewer")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=ROLES, default=FUNDER)
    paypal_email = models.EmailField(blank=True)  # sandbox account used for funding
    country = models.CharField(max_length=2, blank=True)  # ISO 3166-1 alpha-2
    phone = models.CharField(max_length=16, blank=True, validators=[validate_e164])

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["user", "family"], name="unique_membership")]

    @property
    def can_fund(self):
        return self.role in (self.ADMIN, self.FUNDER)

    def __str__(self):
        return f"{self.user} in {self.family} ({self.role})"
