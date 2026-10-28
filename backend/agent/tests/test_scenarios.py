"""BUILD_SPEC §14 demo scenarios 1–5, end to end with the model, extraction and PayPal mocked."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from agent import chat
from agent.models import ChatMessage, Conversation
from core.testing import Fixtures
from mandates import services
from mandates.models import Approval, BlockedPhone, Evidence, LedgerEntry, Mandate, Request
from payments import last_mile
from payments.models import RailTransaction
from payments.payouts import apply_rail_status

from .fakes import ScriptedChat, call, fake_rails, patch_extractor, say, tools
from .helpers import paid_history, submit


class ScenarioBase(TestCase):
    def setUp(self):
        self.f = Fixtures()
        patcher, self.for_payee = fake_rails()
        self.addCleanup(patcher.stop)
        extractor = patch_extractor()
        extractor.start()
        self.addCleanup(extractor.stop)

    def upload(self, name):
        return services.create_upload(family=self.f.family, data=b"jpeg-bytes", content_type="image/jpeg", name=name)

    def pay_references(self):
        return [c.args[2] for c in self.for_payee.return_value.pay.call_args_list]


class Scenario1InflatedQuote(ScenarioBase):
    def test_inflated_quote_refused_then_revised_quote_paid(self):
        self.f.supplier.phone = "+263770000050"
        self.f.supplier.save()
        mandate = self.f.build_mandate()
        conversation = Conversation.objects.create(family=self.f.family, participant_phone="0770000050")

        quote = self.upload("quote@14")
        script = ScriptedChat(
            tools(call("get_mandates")),
            lambda m: tools(call("create_request", mandate_id=str(mandate.id), product="materials", amount=560,
                                 payee_id=None, beneficiary_id=None, summary_en="Cement for the foundation",
                                 attachments=[{"upload_id": str(quote.id), "kind": "QUOTE"}])),
            say("The quote is above the agreed price. Could you send a revised quote?"))
        chat.run_turn(conversation, "Here is the quote for 40 bags of cement", uploads=[quote], llm_chat=script)
        req = Request.objects.get(channel=Request.CHAT)
        self.assertEqual(req.status, Request.REFUSED)
        self.assertEqual(req.payee, self.f.supplier)
        self.assertEqual(req.risk_assessment.level, "LOW")  # a registered supplier number
        self.assertIn("$14.00", req.latest_decision.reason)
        self.assertEqual(script.tool_results()[-1]["status"], Request.REFUSED)
        self.assertFalse(self.for_payee.return_value.pay.called)

        revised, photo = self.upload("quote@10.50"), self.upload("photo:matches")
        script = ScriptedChat(
            tools(call("create_request", mandate_id=str(mandate.id), product="materials", amount=420,
                       payee_id=None, beneficiary_id=None, summary_en="Cement, revised quote",
                       attachments=[{"upload_id": str(revised.id), "kind": "QUOTE"},
                                    {"upload_id": str(photo.id), "kind": "MILESTONE_PHOTO"}])),
            say("Approved. Payment to the supplier is on its way."))
        chat.run_turn(conversation, "Revised quote at $10.50 a bag and the foundation photo",
                      uploads=[revised, photo], llm_chat=script)
        req = Request.objects.filter(channel=Request.CHAT).latest("created_at")
        self.assertEqual(req.amount, Decimal("420"))
        self.assertEqual(req.status, Request.APPROVED)
        self.assertEqual(self.pay_references(), [f"thuma-{req.id}"])
        self.assertEqual(self.for_payee.return_value.pay.call_args.args[0].identifier, "supplier@example.com")
        apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.PAID)


class Scenario2SchoolFees(ScenarioBase):
    def test_invoice_paid_to_school(self):
        mandate = self.f.mandate(Mandate.IMFUNDO, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}},
            {"kind": "requires_invoice", "params": {}}])
        req = services.submit_request(mandate=mandate, amount=Decimal("320"), product="school_fees",
                                      requester_user=self.f.owner, payee=self.f.school, idempotency_key="fees",
                                      uploads=[(self.upload("invoice@320"), Evidence.INVOICE)])
        self.assertEqual(req.status, Request.APPROVED)
        self.assertEqual(self.for_payee.return_value.pay.call_args.args[0].identifier, "school@example.com")


class Scenario3NoDoubleTopUp(ScenarioBase):
    def test_second_funder_refused_with_name_and_alternative(self):
        a, _, c = self.f.funders
        mandate = self.f.support_mandate(extra_rules=[
            {"kind": "cap_per_period", "params": {"amount": 30, "period": "month", "product": "bundles",
                                                  "shared": True}},
            {"kind": "min_interval", "params": {"hours": 24, "product": "bundles"}}])
        first = submit(self.f, mandate, "10", "bundles", user=c)
        tx = apply_rail_status(first.rail_transactions.get(), RailTransaction.SUCCESS)
        last_mile.advance(tx, now=tx.created_at + timedelta(seconds=10))
        tx.refresh_from_db()
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERED)

        conversation = Conversation.objects.create(family=self.f.family, participant_user=a)
        script = ScriptedChat(
            tools(call("create_request", mandate_id=str(mandate.id), product="bundles", amount=10, payee_id=None,
                       beneficiary_id=str(self.f.beneficiary.id), summary_en="Bundles", attachments=[])),
            say("Funder3 already covered bundles today. Would you like to send airtime instead?"))
        chat.run_turn(conversation, "Buy bundles for her", llm_chat=script)
        result = script.tool_results()[-1]
        self.assertEqual(result["status"], Request.REFUSED)
        self.assertIn("Funder3", result["failed_rules"][0])


class Scenario4FraudCaught(ScenarioBase):
    SCAM = "Mwanami, I'm at the hospital, please send $150 to 0771234567, the agent will help me, hurry"

    def test_scam_held_reported_and_number_blocked(self):
        mandate = self.f.support_mandate(extra_rules=[
            {"kind": "cap_per_period", "params": {"amount": 100, "period": "month", "product": "cash",
                                                  "shared": True}}])
        paid_history(self.f, mandate, [10, 10, 8, 12])
        ai = {"stated_intent": "Hospital emergency", "ai_risk": 85, "summary": "Classic emergency impersonation",
              "suggested_verification": "Ask whether she is in hospital",
              "flags": [{"flag": "URGENCY_PRESSURE", "reason": "Pushes to hurry", "quote": "hurry"},
                        {"flag": "IMPERSONATION", "reason": "New number claiming to be her", "quote": "Mwanami"},
                        {"flag": "THIRD_PARTY_PAYMENT", "reason": "Pay another number", "quote": "send $150 to 0771234567"}]}
        conversation = Conversation.objects.create(family=self.f.family, participant_phone="+263719999999")
        script = ScriptedChat(
            tools(call("get_beneficiaries")),
            lambda m: tools(call("create_request", mandate_id=str(mandate.id), product="cash", amount=150,
                                 payee_id=None, beneficiary_id=str(self.f.beneficiary.id),
                                 summary_en="Emergency cash for hospital", attachments=[])),
            say("Your family will confirm this with you shortly."))
        with mock.patch("agent.fraud.default_intent_analyzer", return_value=lambda ctx: ai):
            chat.run_turn(conversation, self.SCAM, llm_chat=script)

        req = Request.objects.get(channel=Request.CHAT)
        risk = req.risk_assessment
        self.assertEqual(req.status, Request.HELD_FRAUD)
        self.assertTrue({"UNREGISTERED_SENDER", "PAYEE_NUMBER_IN_MESSAGE", "AMOUNT_SPIKE"}
                        <= {s["signal"] for s in risk.signals})
        self.assertEqual({f["flag"] for f in risk.ai_flags}, {"URGENCY_PRESSURE", "IMPERSONATION",
                                                              "THIRD_PARTY_PAYMENT"})
        self.assertIn(self.f.beneficiary.phone, risk.suggested_verification)
        self.assertNotIn("risk", script.tool_results()[-1])  # the requester never sees the fraud card
        for funder in self.f.funders:
            self.assertIn(req, services.inbox(funder))
        self.assertFalse(self.for_payee.return_value.pay.called)

        services.apply_approval(req, self.f.funders[0], Approval.REPORT_FRAUD, "Called her; she is at home")
        req.refresh_from_db()
        self.assertEqual(req.status, Request.CONFIRMED_FRAUD)
        self.assertEqual(set(BlockedPhone.objects.values_list("phone", flat=True)),
                         {"+263719999999", "+263771234567"})
        self.assertTrue(req.ledger.filter(event=LedgerEntry.FRAUD_CONFIRMED).exists())


class Scenario5CashCollection(ScenarioBase):
    def test_cash_awaiting_collection_then_collected(self):
        mandate = self.f.support_mandate(extra_rules=[{"kind": "escalate_above", "params": {"amount": 50}}])
        req = submit(self.f, mandate, "40", "cash", user=self.f.funders[1])
        self.assertEqual(req.status, Request.APPROVED)
        tx = apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        tx.refresh_from_db()
        self.assertEqual(tx.last_mile_status, RailTransaction.AWAITING_COLLECTION)
        notice = ChatMessage.objects.get(conversation__participant_phone=self.f.beneficiary.phone)
        self.assertIn(tx.collection_code, notice.text)
        self.assertEqual(last_mile.collect(tx, code=tx.collection_code).last_mile_status,
                         RailTransaction.COLLECTED)
