"""Mandates, requests and the audit trail (BUILD_SPEC §4).

Business logic lives in services.py, agent/policy.py and agent/fraud.py; models stay thin.
"""

from django.conf import settings
from django.db import models

from accounts.models import Family
from core.models import BaseModel, currency_field, money_field
from core.phones import validate_e164

User = settings.AUTH_USER_MODEL


def default_timezone():
    return settings.TIME_ZONE


class Beneficiary(BaseModel):
    """Someone the family supports. Has no user account; identified by a registered phone number."""

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="beneficiaries")
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=16, validators=[validate_e164])
    allowed_products = models.JSONField(default=list, blank=True)  # e.g. ["airtime", "bundles", "cash"]
    timezone = models.CharField(max_length=40, default=default_timezone)
    registered_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    phone_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name_plural = "beneficiaries"

    def __str__(self):
        return self.name


class Payee(BaseModel):
    """Who money is paid to: a supplier, school, mobile money provider or biller."""

    SUPPLIER = "SUPPLIER"
    SCHOOL = "SCHOOL"
    MOBILE_MONEY_PROVIDER = "MOBILE_MONEY_PROVIDER"
    FUNERAL_PROVIDER = "FUNERAL_PROVIDER"
    MEDICAL_AID = "MEDICAL_AID"
    OTHER = "OTHER"
    KINDS = [(k, k.replace("_", " ").title()) for k in
             (SUPPLIER, SCHOOL, MOBILE_MONEY_PROVIDER, FUNERAL_PROVIDER, MEDICAL_AID, OTHER)]

    PAYPAL_PAYOUT = "PAYPAL_PAYOUT"
    LOCAL_MOBILE_MONEY = "LOCAL_MOBILE_MONEY"
    BILLER_SIM = "BILLER_SIM"
    RAILS = [(PAYPAL_PAYOUT, "PayPal Payout"), (LOCAL_MOBILE_MONEY, "Local mobile money"),
             (BILLER_SIM, "Biller (simulated rail)")]

    family = models.ForeignKey(Family, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="payees")  # null = shared registry
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=24, choices=KINDS)
    rail = models.CharField(max_length=20, choices=RAILS, default=PAYPAL_PAYOUT)
    paypal_email = models.EmailField(blank=True)
    external_ref = models.CharField(max_length=120, blank=True)  # biller account number etc.
    verified = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Mandate(BaseModel):
    AKHA = "AKHA"
    IMFUNDO = "IMFUNDO"
    ISIKHWAMA = "ISIKHWAMA"
    ISILILO = "ISILILO"
    VIKELA = "VIKELA"
    TYPES = [(AKHA, "Akha (Build)"), (IMFUNDO, "Imfundo (School fees)"),
             (ISIKHWAMA, "Isikhwama (Shared support)"), (ISILILO, "Isililo (Funeral)"),
             (VIKELA, "Vikela (Health)")]

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    STATUSES = [(s, s.title()) for s in (DRAFT, ACTIVE, PAUSED, CLOSED)]

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="mandates")
    type = models.CharField(max_length=10, choices=TYPES)
    title = models.CharField(max_length=160)
    purpose_text = models.TextField(blank=True)  # the funder's original plain-language request
    currency = currency_field()
    status = models.CharField(max_length=8, choices=STATUSES, default=DRAFT)
    expires_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    signature = models.CharField(max_length=64, blank=True)  # hex HMAC-SHA256, see signing.py
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    funders = models.ManyToManyField(User, through="MandateFunder", related_name="funded_mandates")

    def __str__(self):
        return self.title


class Rule(BaseModel):
    """One rule of a mandate. Kinds and params are listed in templates.RULE_PARAMS."""

    mandate = models.ForeignKey(Mandate, on_delete=models.CASCADE, related_name="rules")
    kind = models.CharField(max_length=32)
    params = models.JSONField(default=dict, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return f"{self.kind} {self.params}"


class MandateFunder(BaseModel):
    OWNER = "OWNER"
    CO_FUNDER = "CO_FUNDER"
    ROLES = [(OWNER, "Owner"), (CO_FUNDER, "Co-funder")]

    mandate = models.ForeignKey(Mandate, on_delete=models.CASCADE, related_name="mandate_funders")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mandate_funder_roles")
    role = models.CharField(max_length=10, choices=ROLES, default=CO_FUNDER)

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["mandate", "user"], name="unique_mandate_funder")]


class Funding(BaseModel):
    PAYPAL = "PAYPAL"
    PAYNOW_INBOUND = "PAYNOW_INBOUND"
    RAILS = [(PAYPAL, "PayPal"), (PAYNOW_INBOUND, "Paynow (test mode)")]

    CREATED = "CREATED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    STATUSES = [(s, s.title()) for s in (CREATED, CAPTURED, FAILED)]

    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="fundings")
    funder = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="fundings")  # null for local Paynow contributors
    amount = money_field()
    rail = models.CharField(max_length=16, choices=RAILS, default=PAYPAL)
    external_id = models.CharField(max_length=64, blank=True)  # PayPal order / capture id
    status = models.CharField(max_length=10, choices=STATUSES, default=CREATED)


class Request(BaseModel):
    """A request to spend from a mandate. Creating one never moves money."""

    CHAT = "CHAT"
    APP = "APP"
    SCHEDULE = "SCHEDULE"
    CHANNELS = [(c, c.title()) for c in (CHAT, APP, SCHEDULE)]

    NEW = "NEW"
    ASSESSED = "ASSESSED"
    APPROVED = "APPROVED"  # decided to pay; payout pending
    REFUSED = "REFUSED"
    ESCALATED = "ESCALATED"
    HELD_FRAUD = "HELD_FRAUD"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    STATUSES = [(s, s.replace("_", " ").title()) for s in
                (NEW, ASSESSED, APPROVED, REFUSED, ESCALATED, HELD_FRAUD, PAID, FAILED, CANCELLED, CONFIRMED_FRAUD)]
    # Statuses whose amount counts against balances, caps and intervals.
    COMMITTED = (APPROVED, PAID)

    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="requests")
    channel = models.CharField(max_length=10, choices=CHANNELS, default=APP)
    requester_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="requests")
    requester_phone = models.CharField(max_length=16, blank=True)
    requester_display = models.CharField(max_length=120, blank=True)
    beneficiary = models.ForeignKey(Beneficiary, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="requests")
    payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.PROTECT, related_name="requests")
    product = models.CharField(max_length=32, blank=True)
    amount = money_field()
    message_text = models.TextField(blank=True)
    summary_en = models.TextField(blank=True)  # English summary when the message is in another language
    idempotency_key = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=NEW)

    @property
    def latest_decision(self):
        return self.decisions.order_by("-created_at").first()

    def __str__(self):
        return f"{self.product or 'request'} {self.amount} ({self.status})"


class Evidence(BaseModel):
    QUOTE = "QUOTE"
    INVOICE = "INVOICE"
    MILESTONE_PHOTO = "MILESTONE_PHOTO"
    RECEIPT = "RECEIPT"
    OTHER = "OTHER"
    KINDS = [(k, k.replace("_", " ").title()) for k in (QUOTE, INVOICE, MILESTONE_PHOTO, RECEIPT, OTHER)]

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=16, choices=KINDS)
    file = models.FileField(upload_to="evidence/%Y/%m/", blank=True)
    extracted = models.JSONField(default=dict, blank=True)
    model_name = models.CharField(max_length=60, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name_plural = "evidence"


class RiskAssessment(BaseModel):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    LEVELS = [(lvl, lvl.title()) for lvl in (LOW, MEDIUM, HIGH)]

    request = models.OneToOneField(Request, on_delete=models.CASCADE, related_name="risk_assessment")
    score = models.PositiveSmallIntegerField(default=0)
    level = models.CharField(max_length=6, choices=LEVELS, default=LOW)
    signals = models.JSONField(default=list, blank=True)  # [{signal, weight, detail}]
    ai_flags = models.JSONField(default=list, blank=True)  # [{flag, reason, quote}]
    ai_summary = models.TextField(blank=True)
    suggested_verification = models.TextField(blank=True)
    model_name = models.CharField(max_length=60, blank=True)


class Decision(BaseModel):
    APPROVE = "APPROVE"
    REFUSE = "REFUSE"
    ESCALATE = "ESCALATE"
    HOLD_FRAUD = "HOLD_FRAUD"
    OUTCOMES = [(o, o.replace("_", " ").title()) for o in (APPROVE, REFUSE, ESCALATE, HOLD_FRAUD)]
    POLICY = "POLICY"

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="decisions")
    outcome = models.CharField(max_length=10, choices=OUTCOMES)
    rule_results = models.JSONField(default=list, blank=True)  # [{rule_id, kind, passed, detail}]
    reason = models.TextField()
    decided_by = models.CharField(max_length=40, default=POLICY)  # "POLICY" or a user id


class Approval(BaseModel):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    VERIFIED_SAFE = "VERIFIED_SAFE"
    REPORT_FRAUD = "REPORT_FRAUD"
    ACTIONS = [(a, a.replace("_", " ").title()) for a in (APPROVE, REJECT, VERIFIED_SAFE, REPORT_FRAUD)]

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="approvals")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approvals")
    action = models.CharField(max_length=14, choices=ACTIONS)
    note = models.TextField(blank=True)


class BlockedPhone(BaseModel):
    """A number reported as fraudulent. Requests mentioning or coming from it are held."""

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="blocked_phones")
    phone = models.CharField(max_length=16, validators=[validate_e164])
    reason = models.TextField(blank=True)
    request = models.ForeignKey(Request, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["family", "phone"], name="unique_blocked_phone")]


class LedgerEntry(BaseModel):
    """Append-only audit log. Every state change writes one; entries are never updated or deleted."""

    FUNDED = "FUNDED"
    REQUESTED = "REQUESTED"
    ASSESSED = "ASSESSED"
    DECIDED = "DECIDED"
    APPROVED_BY_FUNDER = "APPROVED_BY_FUNDER"
    PAID = "PAID"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    FRAUD_HELD = "FRAUD_HELD"
    FRAUD_CONFIRMED = "FRAUD_CONFIRMED"
    RULES_CHANGED = "RULES_CHANGED"
    EVENTS = [(e, e.replace("_", " ").title()) for e in
              (FUNDED, REQUESTED, ASSESSED, DECIDED, APPROVED_BY_FUNDER, PAID, DELIVERED, FAILED,
               FRAUD_HELD, FRAUD_CONFIRMED, RULES_CHANGED)]

    family = models.ForeignKey(Family, on_delete=models.PROTECT, related_name="ledger")
    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="ledger")
    request = models.ForeignKey(Request, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger")
    event = models.CharField(max_length=20, choices=EVENTS)
    amount = money_field(null=True, blank=True)
    actor = models.CharField(max_length=120)  # "POLICY", "SYSTEM", "PAYPAL" or a user id
    data = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name_plural = "ledger entries"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Ledger entries are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Ledger entries are append-only")
