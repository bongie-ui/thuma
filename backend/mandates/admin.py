from django.contrib import admin

from .models import (Approval, Beneficiary, BlockedPhone, Decision, Evidence, Funding, LedgerEntry, Mandate,
                     MandateFunder, Payee, Request, RiskAssessment, Rule)


class RuleInline(admin.TabularInline):
    model = Rule
    extra = 0


class MandateFunderInline(admin.TabularInline):
    model = MandateFunder
    extra = 0


@admin.register(Mandate)
class MandateAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "family", "status", "version", "currency", "expires_at")
    list_filter = ("type", "status")
    readonly_fields = ("version", "signature")
    inlines = [RuleInline, MandateFunderInline]


@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("name", "family", "relationship", "phone", "phone_changed_at")


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "rail", "family", "verified")
    list_filter = ("kind", "rail", "verified")


@admin.register(Funding)
class FundingAdmin(admin.ModelAdmin):
    list_display = ("mandate", "funder", "amount", "rail", "status", "created_at")
    list_filter = ("rail", "status")


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 0


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0


class ApprovalInline(admin.TabularInline):
    model = Approval
    extra = 0


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("mandate", "product", "amount", "requester_display", "status", "created_at")
    list_filter = ("status", "channel")
    inlines = [EvidenceInline, DecisionInline, ApprovalInline]


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("request", "score", "level", "created_at")
    list_filter = ("level",)


@admin.register(BlockedPhone)
class BlockedPhoneAdmin(admin.ModelAdmin):
    list_display = ("phone", "family", "created_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "mandate", "amount", "actor")
    list_filter = ("event",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([Evidence, Decision, Approval, MandateFunder, Rule])
