from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from accounts.models import Membership
from agent.fraud import PHONE_CHANGE_WINDOW
from agent.policy import person
from mandates import signing
from payments.models import RailTransaction

from . import services
from .describe import describe_rule
from .models import (Approval, Beneficiary, Decision, Evidence, LedgerEntry, Mandate, Payee, Request,
                     RiskAssessment, Rule)
from .templates import TEMPLATES

User = get_user_model()


def display_name(user):
    return user.get_full_name() or user.username


def payee_is_simulated(payee):
    """Billers are fully simulated; local mobile money has a simulated last mile."""
    return payee.rail != Payee.PAYPAL_PAYOUT


class MemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id")
    username = serializers.CharField(source="user.username")
    name = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["user_id", "username", "name", "role", "country", "phone", "paypal_email"]

    def get_name(self, m):
        return display_name(m.user)


class BeneficiarySerializer(serializers.ModelSerializer):
    phone_recently_changed = serializers.SerializerMethodField()

    class Meta:
        model = Beneficiary
        fields = ["id", "name", "relationship", "phone", "allowed_products", "timezone", "verified_at",
                  "phone_changed_at", "phone_recently_changed"]
        read_only_fields = ["verified_at", "phone_changed_at", "timezone"]

    def get_phone_recently_changed(self, b):
        return bool(b.phone_changed_at and timezone.now() - b.phone_changed_at < PHONE_CHANGE_WINDOW)


class PayeeSerializer(serializers.ModelSerializer):
    shared = serializers.SerializerMethodField()
    simulated = serializers.SerializerMethodField()
    rail_label = serializers.CharField(source="get_rail_display", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Payee
        fields = ["id", "name", "kind", "kind_label", "rail", "rail_label", "paypal_email", "external_ref", "phone",
                  "verified", "shared", "simulated"]
        read_only_fields = ["verified"]

    def get_shared(self, p):
        return p.family_id is None

    def get_simulated(self, p):
        return payee_is_simulated(p)


class RuleSerializer(serializers.ModelSerializer):
    text = serializers.SerializerMethodField()

    class Meta:
        model = Rule
        fields = ["id", "kind", "params", "position", "text"]

    def get_text(self, rule):
        return describe_rule(rule.kind, rule.params, rule.mandate.currency)


class MandateSerializer(serializers.ModelSerializer):
    type_label = serializers.SerializerMethodField()
    rules = RuleSerializer(many=True, read_only=True)
    balance = serializers.SerializerMethodField()
    funded = serializers.SerializerMethodField()
    funders = serializers.SerializerMethodField()
    signature_valid = serializers.SerializerMethodField()
    beneficiary_ids = serializers.SerializerMethodField()
    pending = serializers.SerializerMethodField()

    class Meta:
        model = Mandate
        fields = ["id", "type", "type_label", "title", "purpose_text", "status", "currency", "version",
                  "signature_valid", "expires_at", "created_at", "balance", "funded", "funders", "rules",
                  "beneficiary_ids", "pending"]

    def get_type_label(self, m):
        return TEMPLATES[m.type].label

    def get_balance(self, m):
        return f"{services.mandate_balance(m):.2f}"

    def get_funded(self, m):
        return f"{services.captured_total(m):.2f}"

    def get_funders(self, m):
        contributions = services.funder_contributions(m)
        return [{"user_id": f.user_id, "name": display_name(f.user), "role": f.role,
                 "contributed": f"{contributions.get(f.user_id, 0):.2f}"}
                for f in m.mandate_funders.select_related("user").order_by("created_at")]

    def get_signature_valid(self, m):
        return signing.verify(m)

    def get_beneficiary_ids(self, m):
        return [str(i) for r in m.rules.all() if r.kind == "allowed_beneficiaries"
                for i in r.params.get("beneficiary_ids", [])]

    def get_pending(self, m):
        return m.requests.filter(status__in=(Request.ESCALATED, Request.HELD_FRAUD)).count()


class RailTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RailTransaction
        fields = ["id", "rail", "amount", "reference", "external_id", "simulated", "status", "last_mile_status",
                  "collection_code", "created_at", "updated_at"]


class RequestSerializer(serializers.ModelSerializer):
    """Summary row for lists and cards."""

    mandate_title = serializers.CharField(source="mandate.title")
    mandate_type = serializers.CharField(source="mandate.type")
    currency = serializers.CharField(source="mandate.currency")
    requester = serializers.SerializerMethodField()
    beneficiary_name = serializers.SerializerMethodField()
    payee_name = serializers.SerializerMethodField()
    payee_simulated = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()
    risk = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = ["id", "mandate", "mandate_title", "mandate_type", "currency", "channel", "requester",
                  "requester_phone", "beneficiary", "beneficiary_name", "payee", "payee_name", "payee_simulated",
                  "product", "amount", "message_text", "summary_en", "status", "created_at", "decision", "risk",
                  "payment"]

    def get_requester(self, r):
        return person(r)

    def get_beneficiary_name(self, r):
        return r.beneficiary.name if r.beneficiary else None

    def get_payee_name(self, r):
        return r.payee.name if r.payee else None

    def get_payee_simulated(self, r):
        return payee_is_simulated(r.payee) if r.payee else False

    def get_decision(self, r):
        d = r.latest_decision
        return {"outcome": d.outcome, "reason": d.reason, "decided_by": d.decided_by} if d else None

    def get_risk(self, r):
        try:
            risk = r.risk_assessment
        except RiskAssessment.DoesNotExist:
            return None
        return {"level": risk.level, "score": risk.score, "signals": risk.signals, "ai_flags": risk.ai_flags,
                "ai_summary": risk.ai_summary, "suggested_verification": risk.suggested_verification,
                "model_name": risk.model_name}

    def get_payment(self, r):
        tx = r.rail_transactions.order_by("-created_at").first()
        return RailTransactionSerializer(tx).data if tx else None


class EvidenceSerializer(serializers.ModelSerializer):
    upload_id = serializers.UUIDField(source="upload.id", allow_null=True, default=None)
    upload_name = serializers.CharField(source="upload.name", allow_null=True, default=None)
    content_type = serializers.CharField(source="upload.content_type", allow_null=True, default=None)

    class Meta:
        model = Evidence
        fields = ["id", "kind", "upload_id", "upload_name", "content_type", "extracted", "model_name", "created_at"]


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Decision
        fields = ["id", "outcome", "reason", "rule_results", "decided_by", "created_at"]


class ApprovalSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Approval
        fields = ["id", "user", "user_name", "action", "note", "created_at"]

    def get_user_name(self, a):
        return display_name(a.user)


class RequestDetailSerializer(RequestSerializer):
    evidence = EvidenceSerializer(many=True, read_only=True)
    decisions = DecisionSerializer(many=True, read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    rail_transactions = RailTransactionSerializer(many=True, read_only=True)
    allowed_actions = serializers.SerializerMethodField()

    class Meta(RequestSerializer.Meta):
        fields = RequestSerializer.Meta.fields + ["evidence", "decisions", "approvals", "rail_transactions",
                                                  "allowed_actions"]

    def get_allowed_actions(self, r):
        return sorted(services.ALLOWED_ACTIONS.get(r.status, ()))


class LedgerEntrySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    mandate_title = serializers.CharField(source="mandate.title")

    class Meta:
        model = LedgerEntry
        fields = ["id", "event", "mandate", "mandate_title", "request", "amount", "actor", "actor_name", "data",
                  "created_at"]

    def get_actor_name(self, e):
        names = self.context.get("user_names", {})
        if e.actor.isdigit():
            return names.get(int(e.actor), "A family member")
        return {"POLICY": "Policy engine", "SYSTEM": "Thuma", "PAYPAL": "PayPal",
                "SIMULATED_RAIL": "Local mobile money (simulated rail)"}.get(e.actor, e.actor)
