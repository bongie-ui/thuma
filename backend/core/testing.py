"""Generic test fixtures. Never use demo-family data in tests (CLAUDE.md rule 3)."""

from decimal import Decimal

from django.contrib.auth import get_user_model

from accounts.models import Family, Membership
from mandates import services
from mandates.models import Funding, Mandate, Payee


class Fixtures:
    """Builds a family with funders, a beneficiary and payees. Use from TestCase.setUp."""

    def __init__(self, n_funders=3):
        User = get_user_model()
        self.funders = [User.objects.create_user(f"funder{i}", password="x", first_name=f"Funder{i}")
                        for i in range(1, n_funders + 1)]
        self.owner = self.funders[0]
        self.family = Family.objects.create(name="Test family", created_by=self.owner)
        for i, user in enumerate(self.funders, start=1):
            Membership.objects.create(user=user, family=self.family, role=Membership.ADMIN if i == 1 else
                                      Membership.FUNDER, phone=f"+1555000000{i}")
        self.beneficiary = services.register_beneficiary(
            family=self.family, name="Test Beneficiary", phone="+263770000099", registered_by=self.owner,
            allowed_products=["airtime", "bundles", "cash"])
        self.supplier = Payee.objects.create(family=self.family, name="Test Supplier", kind=Payee.SUPPLIER,
                                             paypal_email="supplier@example.com", verified=True)
        self.school = Payee.objects.create(family=self.family, name="Test School", kind=Payee.SCHOOL,
                                           paypal_email="school@example.com", verified=True)
        self.provider = Payee.objects.create(name="Mobile Money Provider", kind=Payee.MOBILE_MONEY_PROVIDER,
                                             rail=Payee.LOCAL_MOBILE_MONEY, paypal_email="momo@example.com",
                                             verified=True)

    def mandate(self, type, rules, fund=Decimal("1000"), funders=None, **kwargs):
        funders = self.funders if funders is None else funders
        mandate = services.create_mandate(family=self.family, type=type, title=f"Test {type}", rules=rules,
                                          created_by=funders[0], co_funders=funders[1:], **kwargs)
        if fund:
            self.fund(mandate, funders[0], fund)
        return mandate

    def fund(self, mandate, funder, amount):
        funding = services.create_funding(mandate, funder, Decimal(amount), external_id="TEST-ORDER")
        return services.mark_funding_captured(funding, external_id="TEST-CAPTURE")

    def build_mandate(self, **kwargs):
        return self.mandate(Mandate.AKHA, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.supplier.id)]}},
            {"kind": "max_per_request", "params": {"amount": 600}},
            {"kind": "price_ceiling", "params": {"item": "cement_bag", "max_unit_price": 11.0}},
            {"kind": "requires_evidence", "params": {"kind": "MILESTONE_PHOTO", "label": "foundation complete"}},
        ], **kwargs)

    def support_mandate(self, extra_rules=(), **kwargs):
        return self.mandate(Mandate.ISIKHWAMA, [
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": [str(self.beneficiary.id)]}},
            {"kind": "allowed_products", "params": {"products": ["airtime", "bundles", "cash"]}},
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.provider.id)]}},
            *extra_rules,
        ], **kwargs)
