from django.contrib import admin

from .models import Family, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "family", "role", "country", "paypal_email")
    list_filter = ("role", "country")
