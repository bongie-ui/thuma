from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from agent import policy
from core.testing import Fixtures
from mandates import services
from mandates.models import Approval, BlockedPhone, Decision, Evidence, LedgerEntry, Mandate, Request
from payments import payouts
from payments.models import RailTransaction

from .helpers import fake_pay, midday, paid_history, submit

FOUNDATION_OK = {"kind": Evidence.MILESTONE_PHOTO, "extracted": {"verdict": "matches", "observed": "slab poured"}}


def quote(unit_price, name="Cement 50kg bag"):
    return {"kind": Evidence.QUOTE, "extracted": {"supplier": "Test Supplier", "items": [
        {"name": name, "quantity": 40, "unit_price": unit_price}, {"name": "Bricks", "quantity": 500,
                                                                   "unit_price": 0.3}]}}


def kinds(req, passed):
    return {r["kind"] for r in req.latest_decision.rule_results if r["passed"] is passed}


class BuildMandateRuleTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.build_mandate()

    def build(self, amount="450", evidence=(quote(10.50), FOUNDATION_OK), payee=None):
        return submit(self.f, self.mandate, amount, product="materials", beneficiary=None,
                      payee=payee or self.f.supplier, evidence=evidence)

    def test_all_rules_pass_approves_and_pays(self):
        req = self.build()
        self.assertEqual(req.latest_decision.outcome, Decision.APPROVE)
        self.assertEqual(req.status, Request.APPROVED)  # payout pending
        tx = req.rail_transactions.get()
        self.assertEqual(tx.reference, f"thuma-{req.id}")

    def test_price_ceiling_fails(self):
        req = self.build(evidence=(quote(14), FOUNDATION_OK))
        self.assertEqual(req.status, Request.REFUSED)
        self.assertEqual(kinds(req, False), {"price_ceiling"})
        self.assertIn("$14.00", req.latest_decision.reason)
        self.assertIn("$11.00", req.latest_decision.reason)
        self.assertFalse(req.rail_transactions.exists())

    def test_price_ceiling_needs_a_quote(self):
        req = self.build(evidence=(FOUNDATION_OK,))
        self.assertIn("price_ceiling", kinds(req, False))

    def test_price_ceiling_ignores_other_items(self):
        req = self.build(evidence=(quote(99, name="Roofing sheet"), FOUNDATION_OK))
        self.assertIn("price_ceiling", kinds(req, True))

    def test_milestone_photo_must_match(self):
        bad = {"kind": Evidence.MILESTONE_PHOTO, "extracted": {"verdict": "unclear", "observed": "a field"}}
        req = self.build(evidence=(quote(10), bad))
        self.assertEqual(kinds(req, False), {"requires_evidence"})
        req = self.build(evidence=(quote(10),))
        self.assertEqual(kinds(req, False), {"requires_evidence"})

    def test_max_per_request(self):
        req = self.build(amount="601")
        self.assertIn("max_per_request", kinds(req, False))

    def test_payee_not_allowed(self):
        req = self.build(payee=self.f.school)
        self.assertIn("allowed_payees", kinds(req, False))

    def test_revised_quote_on_same_request(self):
        req = self.build(evidence=(quote(14), FOUNDATION_OK))
        self.assertEqual(req.status, Request.REFUSED)
        req.evidence.create(kind=Evidence.QUOTE, extracted=quote(10.50)["extracted"])
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            req = services.reassess(req, intent_analyzer=lambda c: {"ai_risk": 0}, now=midday())
        self.assertEqual(req.status, Request.APPROVED)

    def test_signature_tamper_refuses(self):
        rule = self.mandate.rules.get(kind="max_per_request")
        rule.params = {"amount": 100000}
        rule.save()
        req = self.build()
        self.assertEqual(req.status, Request.REFUSED)
        self.assertIn("signature", req.latest_decision.reason)

    def test_insufficient_funds(self):
        mandate = self.f.build_mandate(fund=Decimal("100"))
        req = submit(self.f, mandate, "450", product="materials", beneficiary=None, payee=self.f.supplier,
                     evidence=(quote(10), FOUNDATION_OK))
        self.assertEqual(req.status, Request.REFUSED)
        self.assertIn("Insufficient mandate funds: $100.00", req.latest_decision.reason)

    def test_balance_counts_pending_payouts(self):
        self.build(amount="600")  # approved, payout pending
        req = self.build(amount="500")
        self.assertIn("Insufficient", req.latest_decision.reason)

    def test_paused_or_expired_mandate_refuses(self):
        Mandate.objects.filter(pk=self.mandate.pk).update(status=Mandate.PAUSED)
        self.assertIn("paused", self.build().latest_decision.reason)
        Mandate.objects.filter(pk=self.mandate.pk).update(status=Mandate.ACTIVE)
        mandate = self.f.build_mandate(expires_at=timezone.now() - timedelta(days=1))
        req = submit(self.f, mandate, "100", beneficiary=None, payee=self.f.supplier,
                     evidence=(quote(10), FOUNDATION_OK))
        self.assertIn("expired", req.latest_decision.reason)

    def test_policy_requires_risk_assessment(self):
        req = Request.objects.create(mandate=self.mandate, amount=Decimal("10"), idempotency_key="no-risk",
                                     payee=self.f.supplier)
        with self.assertRaises(ValueError):
            policy.check(req)


class InvoiceRuleTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}},
        ])

    def fees(self, amount, supplier="Test School", total=None):
        invoice = {"kind": Evidence.INVOICE, "extracted": {"supplier": supplier, "total": total or amount}}
        return submit(self.f, self.mandate, amount, product="school_fees", beneficiary=None,
                      payee=self.f.school, evidence=(invoice,))

    def test_matching_invoice_approves(self):
        self.assertEqual(self.fees("320").status, Request.APPROVED)

    def test_total_mismatch(self):
        req = self.fees("320", total="300")
        self.assertIn("does not match", req.latest_decision.reason)

    def test_wrong_supplier(self):
        req = self.fees("320", supplier="Someone Else Ltd")
        self.assertIn("not the payee", req.latest_decision.reason)

    def test_missing_invoice(self):
        req = submit(self.f, self.mandate, "320", beneficiary=None, payee=self.f.school)
        self.assertEqual(kinds(req, False), {"requires_invoice"})


class SharedSupportTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.a, self.b, self.c = self.f.funders
        self.mandate = self.f.support_mandate(extra_rules=[
            {"kind": "cap_per_period", "params": {"amount": 30, "period": "month", "product": "bundles",
                                                  "shared": True}},
            {"kind": "min_interval", "params": {"hours": 24, "product": "bundles"}},
            {"kind": "cap_per_period", "params": {"amount": 20, "period": "month", "product": "airtime"}},
            {"kind": "cap_per_period", "params": {"amount": 100, "period": "month", "product": "cash",
                                                  "shared": True}},
            {"kind": "escalate_above", "params": {"amount": 50}},
        ])

    def test_min_interval_names_the_other_funder(self):
        first = submit(self.f, self.mandate, "10", "bundles", user=self.c)
        self.assertEqual(first.status, Request.APPROVED)
        second = submit(self.f, self.mandate, "10", "bundles", user=self.a)
        self.assertEqual(second.status, Request.REFUSED)
        self.assertEqual(kinds(second, False), {"min_interval"})
        self.assertIn("Funder3", second.latest_decision.reason)

    def test_shared_cap_across_funders(self):
        submit(self.f, self.mandate, "25", "bundles", user=self.a)
        Request.objects.update(created_at=midday() - timedelta(hours=25))  # outside min_interval, same month
        if timezone.localtime(midday() - timedelta(hours=25)).month != timezone.localdate().month:
            self.skipTest("first day of the month")
        req = submit(self.f, self.mandate, "10", "bundles", user=self.b)
        self.assertEqual(kinds(req, False), {"cap_per_period"})
        self.assertIn("$5.00 left", req.latest_decision.reason)

    def test_unshared_cap_is_per_funder(self):
        self.assertEqual(submit(self.f, self.mandate, "15", "airtime", user=self.a).status, Request.APPROVED)
        self.assertEqual(submit(self.f, self.mandate, "15", "airtime", user=self.b).status, Request.APPROVED)
        self.assertEqual(submit(self.f, self.mandate, "10", "airtime", user=self.a).status, Request.REFUSED)

    def test_product_not_allowed_for_beneficiary(self):
        self.f.beneficiary.allowed_products = ["airtime"]
        self.f.beneficiary.save()
        req = submit(self.f, self.mandate, "10", "bundles", user=self.a)
        self.assertIn("allowed_products", kinds(req, False))

    def test_escalate_above_then_funder_approves(self):
        req = submit(self.f, self.mandate, "60", "cash", user=self.a)
        self.assertEqual(req.status, Request.ESCALATED)
        self.assertIn(req, services.inbox(self.b))
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            req = services.apply_approval(req, self.b, Approval.APPROVE)
        self.assertEqual(req.status, Request.APPROVED)
        self.assertEqual(req.rail_transactions.count(), 1)
        self.assertEqual(req.latest_decision.decided_by, str(self.b.pk))

    def test_funder_reject(self):
        req = submit(self.f, self.mandate, "60", "cash", user=self.a)
        req = services.apply_approval(req, self.b, Approval.REJECT, "not now")
        self.assertEqual(req.status, Request.REFUSED)

    def test_hard_refusal_cannot_be_overridden(self):
        req = submit(self.f, self.mandate, "120", "cash", user=self.a)
        self.assertEqual(req.status, Request.REFUSED)
        for action in (Approval.APPROVE, Approval.VERIFIED_SAFE):
            with self.assertRaises(services.ServiceError):
                services.apply_approval(req, self.b, action, "please")
        self.assertFalse(req.rail_transactions.exists())

    def test_non_funder_cannot_approve(self):
        from django.contrib.auth import get_user_model
        req = submit(self.f, self.mandate, "60", "cash", user=self.a)
        with self.assertRaises(services.ServiceError):
            services.apply_approval(req, get_user_model().objects.create_user("stranger"), Approval.APPROVE)

    def test_medium_risk_escalates(self):
        req = submit(self.f, self.mandate, "10", "airtime", requester_phone=self.f.beneficiary.phone,
                     message_text="The man says he needs the PIN to load it")
        self.assertEqual(req.status, Request.ESCALATED)

    def test_idempotent_submit(self):
        first = services.submit_request(mandate=self.mandate, amount=Decimal("5"), idempotency_key="same",
                                        requester_user=self.a, beneficiary=self.f.beneficiary,
                                        payee=self.f.provider, product="airtime",
                                        intent_analyzer=lambda c: {}, now=midday())
        again = services.submit_request(mandate=self.mandate, amount=Decimal("5"), idempotency_key="same",
                                        requester_user=self.a, beneficiary=self.f.beneficiary,
                                        payee=self.f.provider, product="airtime")
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Request.objects.filter(idempotency_key="same").count(), 1)


SCAM = "Mwanami, I'm at the hospital, please send $150 to 0771234567, the agent will help me, hurry"


class FraudHoldTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate(extra_rules=[
            {"kind": "cap_per_period", "params": {"amount": 100, "period": "month", "product": "cash",
                                                  "shared": True}},
        ])
        paid_history(self.f, self.mandate, [10, 10, 8, 12])

    def scam(self, amount="150"):
        return submit(self.f, self.mandate, amount, "cash", requester_phone="+263719999999",
                      requester_display="Unknown number", message_text=SCAM)

    def test_high_risk_is_held_even_when_a_rule_fails(self):
        req = self.scam()
        self.assertEqual(req.status, Request.HELD_FRAUD)
        self.assertEqual(req.latest_decision.outcome, Decision.HOLD_FRAUD)
        self.assertFalse(req.rail_transactions.exists())
        self.assertTrue(req.ledger.filter(event=LedgerEntry.FRAUD_HELD).exists())
        for funder in self.f.funders:
            self.assertIn(req, services.inbox(funder))

    def test_report_fraud_blocks_numbers(self):
        req = services.apply_approval(self.scam(), self.f.funders[1], Approval.REPORT_FRAUD, "Not her")
        self.assertEqual(req.status, Request.CONFIRMED_FRAUD)
        blocked = set(BlockedPhone.objects.values_list("phone", flat=True))
        self.assertEqual(blocked, {"+263719999999", "+263771234567"})
        self.assertTrue(req.ledger.filter(event=LedgerEntry.FRAUD_CONFIRMED).exists())
        follow_up = submit(self.f, self.mandate, "5", "airtime", message_text="use 0771234567 instead")
        self.assertEqual(follow_up.status, Request.HELD_FRAUD)

    def test_verified_safe_needs_a_note(self):
        with self.assertRaises(services.ServiceError):
            services.apply_approval(self.scam(), self.f.owner, Approval.VERIFIED_SAFE, "")

    def test_cannot_plain_approve_a_fraud_hold(self):
        with self.assertRaises(services.ServiceError):
            services.apply_approval(self.scam("50"), self.f.owner, Approval.APPROVE)

    def test_verified_safe_pays_when_rules_pass(self):
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = fake_pay
            req = services.apply_approval(self.scam("50"), self.f.owner, Approval.VERIFIED_SAFE,
                                          "Called her registered number, she confirmed")
        self.assertEqual(req.status, Request.APPROVED)
        self.assertEqual(req.rail_transactions.count(), 1)

    def test_verified_safe_still_refuses_when_rules_fail(self):
        req = services.apply_approval(self.scam("150"), self.f.owner, Approval.VERIFIED_SAFE,
                                      "Called her registered number, she confirmed")
        self.assertEqual(req.status, Request.REFUSED)
        self.assertIn("cap", req.latest_decision.reason)
        self.assertFalse(req.rail_transactions.exists())


class PayoutTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate()

    def test_payout_is_idempotent(self):
        req = submit(self.f, self.mandate, "10", "airtime")
        with mock.patch("payments.rails.for_payee") as for_payee:
            again = payouts.pay_request(req)
            for_payee.return_value.pay.assert_not_called()
        self.assertEqual(again, req.rail_transactions.get())

    def test_success_marks_paid_once(self):
        req = submit(self.f, self.mandate, "10", "airtime")
        tx = req.rail_transactions.get()
        payouts.apply_rail_status(tx, RailTransaction.SUCCESS)
        payouts.apply_rail_status(tx, RailTransaction.SUCCESS)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.PAID)
        self.assertEqual(req.ledger.filter(event=LedgerEntry.PAID).count(), 1)

    def test_rail_error_fails_request(self):
        from payments.rails import RailError
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.pay.side_effect = RailError("receiver unavailable")
            req = services.submit_request(mandate=self.mandate, amount=Decimal("10"), idempotency_key="err",
                                          requester_user=self.f.owner, beneficiary=self.f.beneficiary,
                                          payee=self.f.provider, product="airtime",
                                          intent_analyzer=lambda c: {}, now=midday())
        self.assertEqual(req.status, Request.FAILED)
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("1000"))

    def test_only_approved_requests_can_be_paid(self):
        req = Request.objects.create(mandate=self.mandate, amount=Decimal("10"), idempotency_key="x",
                                     payee=self.f.provider, status=Request.ESCALATED)
        with self.assertRaises(ValueError):
            payouts.pay_request(req)

    def test_failed_payout_frees_balance(self):
        req = submit(self.f, self.mandate, "10", "airtime")
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("990"))
        payouts.apply_rail_status(req.rail_transactions.get(), RailTransaction.FAILED)
        self.assertEqual(services.mandate_balance(self.mandate), Decimal("1000"))
