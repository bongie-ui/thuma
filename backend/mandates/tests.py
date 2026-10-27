from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings

from core.testing import Fixtures

from . import services, signing
from .models import LedgerEntry, Mandate
from .templates import PAYPAL_CHECKOUT, PAYPAL_SUBSCRIPTIONS, RULE_PARAMS, TEMPLATES, get_template, validate_rules


class TemplateTests(SimpleTestCase):
    def test_all_five_types_defined(self):
        self.assertEqual(set(TEMPLATES), {t for t, _ in Mandate.TYPES})

    def test_every_type_is_funded_through_paypal(self):
        for t in TEMPLATES.values():
            self.assertTrue({PAYPAL_CHECKOUT, PAYPAL_SUBSCRIPTIONS} & set(t.funding), t.type)

    def test_required_and_default_rules_are_known_kinds(self):
        for t in TEMPLATES.values():
            for kind in t.required_rules:
                self.assertIn(kind, RULE_PARAMS)
            for rule in t.default_rules:
                self.assertIn(rule["kind"], RULE_PARAMS)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            get_template("NOPE")

    def test_missing_required_rule(self):
        errors = validate_rules(Mandate.IMFUNDO, [{"kind": "allowed_payees", "params": {"payee_ids": ["x"]}}])
        self.assertEqual(len(errors), 1)
        self.assertIn("requires_invoice", errors[0])

    def test_bad_params(self):
        errors = validate_rules(Mandate.VIKELA, [
            {"kind": "allowed_payees", "params": {"payee_ids": []}},
            {"kind": "max_per_request", "params": {"amount": -1, "extra": 1}},
            {"kind": "cap_per_period", "params": {"amount": 10, "period": "fortnight"}},
            {"kind": "teleport", "params": {}},
        ])
        self.assertEqual(len(errors), 5, errors)

    def test_valid_rules(self):
        self.assertEqual(validate_rules(Mandate.ISIKHWAMA, [
            {"kind": "allowed_beneficiaries", "params": {"beneficiary_ids": ["b"]}},
            {"kind": "allowed_products", "params": {"products": ["bundles"]}},
            {"kind": "cap_per_period", "params": {"amount": 30, "period": "month", "product": "bundles",
                                                  "shared": True}},
            {"kind": "min_interval", "params": {"hours": 24, "product": "bundles"}},
        ]), [])


class SigningTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.build_mandate(fund=None)

    def test_new_mandate_is_signed_and_active(self):
        self.assertEqual(self.mandate.status, Mandate.ACTIVE)
        self.assertEqual(len(self.mandate.signature), 64)
        self.assertTrue(signing.verify(self.mandate))

    def test_tampered_rule_fails_verification(self):
        rule = self.mandate.rules.get(kind="max_per_request")
        rule.params = {"amount": 6000}
        rule.save()
        self.assertFalse(signing.verify(self.mandate))

    def test_tampered_expiry_or_version_fails(self):
        self.mandate.version = 7
        self.assertFalse(signing.verify(self.mandate))

    @override_settings(MANDATE_SIGNING_KEY="another-key")
    def test_different_key_fails(self):
        self.assertFalse(signing.verify(self.mandate))

    def test_unsigned_fails(self):
        self.mandate.signature = ""
        self.assertFalse(signing.verify(self.mandate))

    def test_payload_is_canonical(self):
        rules = [{"kind": "b", "params": {"y": 1, "x": 2}, "position": 1}, {"kind": "a", "params": {}, "position": 0}]
        self.assertEqual(signing.canonical_payload(self.mandate, rules),
                         signing.canonical_payload(self.mandate, list(reversed(rules))))

    def test_update_rules_bumps_version_resigns_and_records(self):
        rules = [{"kind": r.kind, "params": r.params} for r in self.mandate.rules.all()]
        rules[1]["params"] = {"amount": 700}
        services.update_rules(self.mandate, rules, self.f.owner)
        self.mandate.refresh_from_db()
        self.assertEqual(self.mandate.version, 2)
        self.assertTrue(signing.verify(self.mandate))
        self.assertEqual(self.mandate.ledger.filter(event=LedgerEntry.RULES_CHANGED).count(), 2)

    def test_only_owner_changes_rules(self):
        with self.assertRaises(services.ServiceError):
            services.update_rules(self.mandate, [], self.f.funders[1])


class MandateServiceTests(TestCase):
    def setUp(self):
        self.f = Fixtures()

    def test_invalid_rules_rejected(self):
        with self.assertRaises(services.ServiceError):
            self.f.mandate(Mandate.IMFUNDO, [], fund=None)

    def test_non_member_cannot_create(self):
        from django.contrib.auth import get_user_model
        outsider = get_user_model().objects.create_user("outsider")
        with self.assertRaises(services.ServiceError):
            services.create_mandate(family=self.f.family, type=Mandate.IMFUNDO, title="x", created_by=outsider,
                                    rules=[{"kind": "allowed_payees", "params": {"payee_ids": ["x"]}},
                                           {"kind": "requires_invoice", "params": {}}])

    def test_balance_and_contributions(self):
        mandate = self.f.support_mandate(fund=Decimal("100"))
        self.f.fund(mandate, self.f.funders[1], "50")
        self.assertEqual(services.mandate_balance(mandate), Decimal("150"))
        contributions = services.funder_contributions(mandate)
        self.assertEqual(contributions[self.f.funders[0].id], Decimal("100"))
        self.assertEqual(contributions[self.f.funders[2].id], Decimal("0"))

    def test_capture_is_idempotent(self):
        mandate = self.f.support_mandate(fund=None)
        funding = services.create_funding(mandate, self.f.owner, "20")
        services.mark_funding_captured(funding)
        services.mark_funding_captured(funding)
        self.assertEqual(mandate.ledger.filter(event=LedgerEntry.FUNDED).count(), 1)
        self.assertEqual(services.mandate_balance(mandate), Decimal("20"))

    def test_phone_change_sets_timestamp(self):
        b = self.f.beneficiary
        self.assertIsNone(b.phone_changed_at)
        services.change_beneficiary_phone(b, "0771112222", self.f.owner)
        self.assertEqual(b.phone, "+263771112222")
        self.assertIsNotNone(b.phone_changed_at)


class LedgerTests(TestCase):
    def test_append_only(self):
        f = Fixtures()
        entry = f.support_mandate(fund=None).ledger.first()
        entry.actor = "someone else"
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(ValueError):
            entry.delete()
