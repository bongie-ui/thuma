"""The demo family (BUILD_SPEC §13). The ONLY place demo people and businesses exist (CLAUDE.md rule 3).

Mandates, beneficiaries and fundings are created through the services. Past paid requests (the AMOUNT_SPIKE
baseline) are history, not new payments: they are written directly and back-dated, and never touch a rail.
"""

import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Family, Membership
from mandates import services
from mandates.models import Decision, LedgerEntry, Mandate, Payee, Request
from payments.models import RailTransaction
from payments.payouts import reference_for

FAMILY = "Fuyana family"
MAMA_PHONE = "+263770000001"  # fake number
# The PayPal sandbox accounts created for the demo (not secrets). An env var with the same name overrides each one.
SANDBOX_EMAILS = {
    "DEMO_FUNDER_1_EMAIL": "mmeli.fuyana@personal.example.com",
    "DEMO_FUNDER_2_EMAIL": "bonginkosi.fuyana@personal.example.com",
    "DEMO_FUNDER_3_EMAIL": "andile.fuyana@personal.example.com",
    "DEMO_PAYEE_HARDWARE_EMAIL": "hardware@business.example.com",
    "DEMO_PAYEE_SCHOOL_EMAIL": "fees@business.example.com",
    "DEMO_PAYEE_MOBILE_MONEY_EMAIL": "mobilemoney@business.example.com",
}


def sandbox_email(var):
    return os.environ.get(var) or SANDBOX_EMAILS.get(var, "")


FUNDERS = [  # username, first, last, country, phone (fake), role, sandbox email (SANDBOX_EMAILS key)
    ("mmeli", "Mmeli", "Fuyana", "ZA", "+27820000001", Membership.ADMIN, "DEMO_FUNDER_1_EMAIL"),
    ("bonginkosi", "Bonginkosi", "Fuyana", "US", "+15550000002", Membership.FUNDER, "DEMO_FUNDER_2_EMAIL"),
    ("andile", "Andile", "Fuyana", "GB", "+447700900003", Membership.FUNDER, "DEMO_FUNDER_3_EMAIL"),
]
PAYEES = [  # key, name, kind, rail, sandbox email (SANDBOX_EMAILS key), phone (for payee chat), external ref
    ("hardware", "Gwanda Hardware", Payee.SUPPLIER, Payee.PAYPAL_PAYOUT, "DEMO_PAYEE_HARDWARE_EMAIL",
     "+263770000010", ""),
    ("school", "Sunrise Academy", Payee.SCHOOL, Payee.PAYPAL_PAYOUT, "DEMO_PAYEE_SCHOOL_EMAIL", "+263770000020", ""),
    ("momo", "Local Mobile Money", Payee.MOBILE_MONEY_PROVIDER, Payee.LOCAL_MOBILE_MONEY,
     "DEMO_PAYEE_MOBILE_MONEY_EMAIL", "", ""),
    ("funeral", "Peaceful Rest Funeral Cover", Payee.FUNERAL_PROVIDER, Payee.BILLER_SIM, "", "", "PRF-000123"),
    ("medical", "Imbali Health Medical Aid", Payee.MEDICAL_AID, Payee.BILLER_SIM, "", "", "IHM-000456"),
]
# Months ago -> [(funder index, product, amount)]: three months of ordinary support for Mama.
HISTORY = {m: [(m % 3, "airtime", 10), ((m + 1) % 3, "bundles", 15), ((m + 2) % 3, "cash", 40)] for m in (1, 2, 3)}


class Command(BaseCommand):
    help = "Create the demo family, its mandates and some history. --reset deletes and recreates it."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="delete the demo family and its users first")

    def handle(self, *args, reset=False, **options):
        if Family.objects.filter(name=FAMILY).exists():
            if not reset:
                raise CommandError(f"{FAMILY} already exists; use --reset to recreate it")
            self._delete()
        with transaction.atomic():
            self._create()
        self.stdout.write(self.style.SUCCESS(f"Seeded {FAMILY}: log in as mmeli, bonginkosi or andile"))

    # --- reset ----------------------------------------------------------------------------------------

    @transaction.atomic
    def _delete(self):
        family = Family.objects.get(name=FAMILY)
        users = [m.user_id for m in family.memberships.all()]
        # Queryset deletes: the ledger is append-only for the app, but a demo reset removes the whole family.
        LedgerEntry.objects.filter(family=family).delete()
        RailTransaction.objects.filter(request__mandate__family=family).delete()
        Request.objects.filter(mandate__family=family).delete()
        for mandate in family.mandates.all():
            mandate.fundings.all().delete()
        family.mandates.all().delete()
        family.delete()
        get_user_model().objects.filter(pk__in=users, is_staff=False, memberships__isnull=True).delete()
        self.stdout.write(f"Deleted {FAMILY}")

    # --- create ---------------------------------------------------------------------------------------

    def _create(self):
        User = get_user_model()
        password = os.environ.get("DEMO_PASSWORD") or None
        funders = []
        for username, first, last, country, phone, role, email_var in FUNDERS:
            if User.objects.filter(username=username).exists():
                raise CommandError(f"A user called {username} already exists outside the demo family")
            user = User.objects.create_user(username, password=password, first_name=first, last_name=last,
                                            email=sandbox_email(email_var))
            funders.append((user, country, phone, role, sandbox_email(email_var)))
        mmeli, bonginkosi, andile = (f[0] for f in funders)

        family = Family.objects.create(name=FAMILY, created_by=mmeli)
        for user, country, phone, role, email in funders:
            Membership.objects.create(user=user, family=family, role=role, country=country, phone=phone,
                                      paypal_email=email)

        mama = services.register_beneficiary(family=family, name="Mama Siqile Fuyana", phone=MAMA_PHONE,
                                             relationship="Mother", registered_by=mmeli,
                                             allowed_products=["airtime", "bundles", "cash"])
        payees = {}
        for key, name, kind, rail, email_var, phone, ref in PAYEES:
            email = sandbox_email(email_var) if email_var else ""
            payees[key] = Payee.objects.create(family=family, name=name, kind=kind, rail=rail, paypal_email=email,
                                               phone=phone, external_ref=ref, verified=True)

        build = services.create_mandate(
            family=family, type=Mandate.AKHA, title="Mama's house: foundation", created_by=bonginkosi,
            co_funders=[mmeli, andile],
            purpose_text="Up to $600 for cement and bricks for Mama's house in Gwanda. Pay the hardware store "
                         "directly, and only after a photo shows the foundation is done. Cement no more than $11 a bag.",
            rules=[{"kind": "allowed_payees", "params": {"payee_ids": [str(payees["hardware"].id)]}},
                   {"kind": "max_per_request", "params": {"amount": 600}},
                   {"kind": "price_ceiling", "params": {"item": "cement_bag", "max_unit_price": 11.0,
                                                        "keywords": ["cement"]}},
                   {"kind": "requires_evidence", "params": {"kind": "MILESTONE_PHOTO",
                                                            "label": "foundation complete"}}])
        fees = services.create_mandate(
            family=family, type=Mandate.IMFUNDO, title="School fees: Sunrise Academy", created_by=andile,
            co_funders=[mmeli],
            purpose_text="Term fees for our niece at Sunrise Academy, paid to the school on its invoice.",
            rules=[{"kind": "allowed_payees", "params": {"payee_ids": [str(payees["school"].id)]}},
                   {"kind": "requires_invoice", "params": {}},
                   {"kind": "max_per_request", "params": {"amount": 400}}])
        support = services.create_mandate(
            family=family, type=Mandate.ISIKHWAMA, title="Support for Mama", created_by=mmeli,
            co_funders=[bonginkosi, andile],
            purpose_text="The three of us share Mama's airtime, data bundles and cash. No double top-ups.",
            rules=[{"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(mama.id)]}},
                   {"kind": "allowed_products", "params": {"products": ["airtime", "bundles", "cash"]}},
                   {"kind": "allowed_payees", "params": {"payee_ids": [str(payees["momo"].id)]}},
                   {"kind": "cap_per_period", "params": {"amount": 30, "period": "month", "product": "bundles",
                                                         "shared": True}},
                   {"kind": "min_interval", "params": {"hours": 24, "product": "bundles"}},
                   {"kind": "cap_per_period", "params": {"amount": 20, "period": "month", "product": "airtime",
                                                         "shared": True}},
                   {"kind": "cap_per_period", "params": {"amount": 100, "period": "month", "product": "cash",
                                                         "shared": True}},
                   {"kind": "escalate_above", "params": {"amount": 50}}])

        for mandate, amounts in ((build, [(bonginkosi, 300), (mmeli, 200), (andile, 100)]),
                                 (fees, [(andile, 250), (mmeli, 150)]),
                                 (support, [(mmeli, 150), (bonginkosi, 150), (andile, 100)])):
            for user, amount in amounts:
                funding = services.create_funding(mandate, user, Decimal(amount), external_id="SEED-ORDER")
                services.mark_funding_captured(funding, external_id=f"SEED-{funding.id.hex[:12].upper()}")

        self._history(support, mama, payees["momo"], [mmeli, bonginkosi, andile])

    def _history(self, mandate, beneficiary, payee, funders):
        now = timezone.now()
        for months_ago, items in HISTORY.items():
            for i, (who, product, amount) in enumerate(items):
                when = now - timedelta(days=35 * months_ago + 3 * i)  # always before this month
                user = funders[who]
                req = Request.objects.create(
                    mandate=mandate, channel=Request.APP, requester_user=user, requester_display=user.first_name,
                    beneficiary=beneficiary, payee=payee, product=product, amount=Decimal(amount),
                    idempotency_key=f"seed-{mandate.id}-{months_ago}-{i}", status=Request.PAID,
                    summary_en=f"{product} for {beneficiary.name}")
                Decision.objects.create(request=req, outcome=Decision.APPROVE, reason="Approved: all rules passed")
                RailTransaction.objects.create(
                    request=req, rail=payee.rail, amount=req.amount, reference=reference_for(req),
                    external_id="SEED-HISTORY", simulated=True, status=RailTransaction.SUCCESS,
                    last_mile_status=(RailTransaction.COLLECTED if product == "cash" else RailTransaction.DELIVERED))
                entries = [services.record(mandate, event, actor, request=req, amount=req.amount, seeded=True)
                           for event, actor in ((LedgerEntry.REQUESTED, str(user.pk)),
                                                (LedgerEntry.DECIDED, Decision.POLICY),
                                                (LedgerEntry.PAID, "SYSTEM"),
                                                (LedgerEntry.DELIVERED, "SIMULATED_RAIL"))]
                # Back-date the history rows created just above so caps and intervals see past periods.
                Request.objects.filter(pk=req.pk).update(created_at=when)
                LedgerEntry.objects.filter(pk__in=[e.pk for e in entries]).update(created_at=when)
