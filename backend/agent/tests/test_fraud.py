from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from agent import fraud
from core.testing import Fixtures
from mandates import services
from mandates.models import BlockedPhone, Request, RiskAssessment

from .helpers import midday, paid_history, quiet_ai

SCAM = "Mwanami, I'm at the hospital, please send $150 to 0771234567, the agent will help me, hurry"


class FraudTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate()
        paid_history(self.f, self.mandate, [10, 10, 8, 12])

    def request(self, amount="10", message="", phone="", user=None, **kwargs):
        return Request.objects.create(mandate=self.mandate, amount=Decimal(amount), product="bundles",
                                      beneficiary=self.f.beneficiary, payee=self.f.provider, message_text=message,
                                      requester_phone=phone, requester_user=user,
                                      idempotency_key=f"r-{Request.objects.count()}", **kwargs)

    def signals(self, assessment):
        return {s["signal"] for s in assessment.signals}

    # The four required tests (BUILD_SPEC §7)

    def test_routine_request_from_registered_beneficiary_is_low(self):
        req = self.request(message="Please buy me bundles", phone=self.f.beneficiary.phone)
        risk = fraud.assess(req, intent_analyzer=quiet_ai, now=midday())
        self.assertEqual(risk.level, RiskAssessment.LOW)
        self.assertEqual(risk.signals, [])

    def test_new_number_hospital_story_is_high_on_rules_alone(self):
        req = self.request(amount="150", message=SCAM, phone="+263719999999")
        risk = fraud.assess(req, intent_analyzer=quiet_ai, now=midday())
        self.assertEqual(risk.level, RiskAssessment.HIGH)
        self.assertTrue({"UNREGISTERED_SENDER", "PAYEE_NUMBER_IN_MESSAGE", "AMOUNT_SPIKE"} <= self.signals(risk))
        self.assertIn(self.f.beneficiary.phone, risk.suggested_verification)

    def test_pin_mentioned_is_at_least_medium(self):
        req = self.request(message="Send me your PIN so I can check the account", phone=self.f.beneficiary.phone)
        risk = fraud.assess(req, intent_analyzer=quiet_ai, now=midday())
        self.assertIn(risk.level, (RiskAssessment.MEDIUM, RiskAssessment.HIGH))
        self.assertIn("CREDENTIALS_MENTIONED", self.signals(risk))

    def test_llm_failure_falls_back_to_rules(self):
        def broken(context):
            raise TimeoutError("model timed out")
        req = self.request(message="Please buy me bundles", phone=self.f.beneficiary.phone)
        risk = fraud.assess(req, intent_analyzer=broken, now=midday())
        self.assertEqual(self.signals(risk), {"AI_UNAVAILABLE"})
        self.assertEqual(risk.score, 10)
        self.assertEqual(risk.level, RiskAssessment.LOW)

    # AI can only add risk

    def test_ai_adds_risk_and_flags(self):
        def worried(context):
            self.assertFalse(context["requester_registered"])
            return {"ai_risk": 80, "summary": "Looks like impersonation",
                    "flags": [{"flag": "IMPERSONATION", "reason": "new number", "quote": "lost my phone"},
                              {"flag": "MADE_UP", "reason": "x", "quote": "y"}]}
        req = self.request(message="I lost my phone, this is my new number", phone="+263719999999")
        risk = fraud.assess(req, intent_analyzer=worried, now=midday())
        self.assertEqual(risk.score, 35 + 40)
        self.assertEqual([f["flag"] for f in risk.ai_flags], ["IMPERSONATION", "OTHER"])

    def test_ai_cannot_lower_risk(self):
        req = self.request(amount="150", message=SCAM, phone="+263719999999")
        risk = fraud.assess(req, intent_analyzer=lambda c: {"ai_risk": -500}, now=midday())
        self.assertEqual(risk.level, RiskAssessment.HIGH)

    def test_ai_verification_cannot_point_to_unregistered_number(self):
        req = self.request(amount="150", message=SCAM, phone="+263719999999")
        risk = fraud.assess(req, intent_analyzer=lambda c: {
            "ai_risk": 50, "suggested_verification": "Call 0771234567 to confirm"}, now=midday())
        self.assertNotIn("+263771234567", risk.suggested_verification)
        self.assertNotIn("0771234567", risk.suggested_verification)

    # Individual signals

    def test_recently_changed_number(self):
        services.change_beneficiary_phone(self.f.beneficiary, "+263770000098", self.f.owner)
        req = self.request(phone=self.f.beneficiary.phone)
        self.assertIn("BENEFICIARY_RECENTLY_CHANGED", self.signals(fraud.assess(req, quiet_ai, now=midday())))
        later = timezone.now() + timedelta(hours=73)
        self.assertNotIn("BENEFICIARY_RECENTLY_CHANGED", self.signals(fraud.assess(req, quiet_ai, now=later)))

    def test_velocity(self):
        self.request(user=self.f.owner)
        self.request(user=self.f.owner)
        req = self.request(user=self.f.owner)
        self.assertIn("VELOCITY", self.signals(fraud.assess(req, quiet_ai, now=midday())))

    def test_no_spike_without_history(self):
        Request.objects.filter(status=Request.PAID).delete()
        req = self.request(amount="150", user=self.f.owner)
        self.assertNotIn("AMOUNT_SPIKE", self.signals(fraud.assess(req, quiet_ai, now=midday())))

    def test_odd_hours(self):
        night = timezone.make_aware(datetime.combine(timezone.localdate(), time(2, 30)))
        req = self.request(user=self.f.owner)
        self.assertIn("ODD_HOURS", self.signals(fraud.assess(req, quiet_ai, now=night)))

    def test_funder_in_app_request_is_not_unregistered(self):
        req = self.request(user=self.f.owner)
        self.assertEqual(fraud.assess(req, quiet_ai, now=midday()).signals, [])

    def test_blocked_number(self):
        BlockedPhone.objects.create(family=self.f.family, phone="+263771234567")
        req = self.request(message="send it to 0771234567", user=self.f.owner)
        risk = fraud.assess(req, quiet_ai, now=midday())
        self.assertIn("BLOCKED_NUMBER", self.signals(risk))
        self.assertEqual(risk.level, RiskAssessment.HIGH)

    def test_reassessment_replaces_previous(self):
        req = self.request(user=self.f.owner)
        fraud.assess(req, quiet_ai, now=midday())
        fraud.assess(req, quiet_ai, now=midday())
        self.assertEqual(RiskAssessment.objects.filter(request=req).count(), 1)
