"""REST API: family scoping, the request pipeline over HTTP, approvals, chat and demo-only endpoints."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from agent.models import Conversation
from agent.tests.fakes import ScriptedChat, call, fake_rails, say, tools
from core.testing import Fixtures
from mandates.models import Request
from payments.models import RailTransaction
from payments.payouts import apply_rail_status

BUNDLES_RULES = [{"kind": "cap_per_period", "params": {"amount": 30, "period": "month", "product": "bundles",
                                                       "shared": True}},
                 {"kind": "min_interval", "params": {"hours": 24, "product": "bundles"}}]


class ApiBase(TestCase):
    def setUp(self):
        self.f = Fixtures()
        patcher, self.for_payee = fake_rails()
        self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.login(self.f.owner)

    def login(self, user):
        self.client.force_authenticate(user)

    def post(self, url, data=None, **kwargs):
        return self.client.post(url, data or {}, format=kwargs.pop("format", "json"), **kwargs)

    def bundles(self, mandate, user=None, key="k1", **extra):
        if user:
            self.login(user)
        return self.post("/api/requests/", {"mandate": str(mandate.id), "product": "bundles", "amount": "15",
                                            "beneficiary": str(self.f.beneficiary.id), "idempotency_key": key,
                                            **extra})


class AuthTests(ApiBase):
    def test_me_sets_csrf_cookie_and_reports_family(self):
        client = APIClient()
        r = client.get("/api/auth/me/")
        self.assertFalse(r.data["authenticated"])
        self.assertIn("csrftoken", r.cookies)
        r = self.client.get("/api/auth/me/")
        self.assertEqual(r.data["user"]["family"]["name"], "Test family")

    def test_api_needs_login(self):
        self.assertEqual(APIClient().get("/api/mandates/").status_code, 403)

    def test_health_is_public(self):
        self.assertEqual(APIClient().get("/api/health/").status_code, 200)

    @override_settings(DEMO_MODE=False)
    def test_demo_login_only_in_demo_mode(self):
        self.assertEqual(APIClient().get("/api/auth/demo-users/").status_code, 404)
        self.assertEqual(APIClient().post("/api/auth/demo-login/", {"username": "funder1"}).status_code, 404)

    @override_settings(DEMO_MODE=True)
    def test_demo_login_offers_members_but_never_staff(self):
        admin = get_user_model().objects.create_superuser("root", password="x")
        self.f.family.memberships.create(user=admin, role="ADMIN")
        client = APIClient()
        names = [u["username"] for u in client.get("/api/auth/demo-users/").data]
        self.assertIn(self.f.funders[1].username, names)
        self.assertNotIn("root", names)
        self.assertEqual(client.post("/api/auth/demo-login/", {"username": "root"}).status_code, 400)
        r = client.post("/api/auth/demo-login/", {"username": self.f.funders[1].username})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(client.get("/api/auth/me/").data["authenticated"])


class MandateApiTests(ApiBase):
    def test_list_shows_rules_in_plain_words_balance_and_contributions(self):
        mandate = self.f.build_mandate()
        [m] = self.client.get("/api/mandates/").data
        self.assertEqual(m["balance"], "1000.00")
        self.assertTrue(m["signature_valid"])
        self.assertIn("Cement bag: no more than $11.00 each", [r["text"] for r in m["rules"]])
        self.assertIn("Pays only Test Supplier", [r["text"] for r in m["rules"]])
        owner = next(x for x in m["funders"] if x["role"] == "OWNER")
        self.assertEqual(owner["contributed"], "1000.00")
        self.assertEqual(m["id"], str(mandate.id))

    def test_create_signs_and_rejects_rules_missing_from_template(self):
        r = self.post("/api/mandates/", {"type": "IMFUNDO", "title": "Fees", "rules": [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.school.id)]}}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("requires_invoice", r.data["detail"])
        r = self.post("/api/mandates/", {"type": "IMFUNDO", "title": "Fees", "co_funder_ids": [self.f.funders[1].id],
                                         "rules": [{"kind": "allowed_payees",
                                                    "params": {"payee_ids": [str(self.f.school.id)]}},
                                                   {"kind": "requires_invoice", "params": {}}]})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["signature_valid"])
        self.assertEqual(len(r.data["funders"]), 2)

    def test_preview_describes_and_validates(self):
        r = self.post("/api/mandates/preview-rules/", {"type": "ISIKHWAMA", "rules": BUNDLES_RULES})
        self.assertIn("Bundles: at most once every 24 hours", [x["text"] for x in r.data["rules"]])
        self.assertTrue(r.data["errors"])  # allowed_beneficiaries and allowed_products are required

    def test_other_familys_data_is_invisible(self):
        mandate = self.f.build_mandate()
        other = Fixtures(prefix="o-")
        self.login(other.owner)
        self.assertEqual(self.client.get("/api/mandates/").data, [])
        self.assertEqual(self.client.get(f"/api/mandates/{mandate.id}/").status_code, 404)
        r = self.bundles(mandate)
        self.assertEqual(r.status_code, 404)

    def test_funding_answers_until_paypal_checkout_is_built(self):
        mandate = self.f.build_mandate()
        self.assertEqual(self.post(f"/api/mandates/{mandate.id}/fund/create-order/").status_code, 503)


class RequestApiTests(ApiBase):
    def test_quick_action_pays_then_second_funder_is_told_who_covered_it(self):
        mandate = self.f.support_mandate(extra_rules=BUNDLES_RULES)
        r = self.bundles(mandate, key="a")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], Request.APPROVED)
        self.assertEqual(r.data["payee_name"], "Mobile Money Provider")  # the mandate's only payee
        self.assertTrue(r.data["payee_simulated"])

        r = self.bundles(mandate, user=self.f.funders[1], key="b")
        self.assertEqual(r.data["status"], Request.REFUSED)
        self.assertIn("Funder1", r.data["decision"]["reason"])

        cov = self.client.get(f"/api/mandates/{mandate.id}/coverage/?beneficiary={self.f.beneficiary.id}").data
        bundles = next(c for c in cov if c["product"] == "bundles")
        self.assertEqual((bundles["cap"], bundles["used"]), ("30", "15.00"))
        self.assertEqual(bundles["covered_by"][0]["by"], "Funder1")

    def test_same_idempotency_key_returns_the_same_request(self):
        mandate = self.f.support_mandate()
        a, b = self.bundles(mandate, key="same"), self.bundles(mandate, key="same")
        self.assertEqual(a.data["id"], b.data["id"])
        self.assertEqual(self.for_payee.return_value.pay.call_count, 1)

    def test_escalation_reaches_inbox_and_funder_approval_pays(self):
        mandate = self.f.support_mandate()
        r = self.bundles(mandate, message_text="Please send it to 0779999999 instead")
        self.assertEqual(r.data["status"], Request.ESCALATED)
        self.assertEqual(r.data["risk"]["level"], "MEDIUM")

        self.login(self.f.funders[1])
        inbox = self.client.get("/api/requests/?inbox=1").data
        self.assertEqual([x["id"] for x in inbox], [r.data["id"]])
        detail = self.client.get(f"/api/requests/{r.data['id']}/").data
        self.assertEqual(detail["allowed_actions"], ["APPROVE", "REJECT", "REPORT_FRAUD"])

        r = self.post(f"/api/requests/{r.data['id']}/approval/", {"action": "APPROVE"})
        self.assertEqual(r.data["status"], Request.APPROVED)
        self.assertEqual(self.client.get("/api/requests/?inbox=1").data, [])

    def test_approval_errors_are_readable(self):
        mandate = self.f.support_mandate()
        url = f"/api/requests/{self.bundles(mandate).data['id']}/approval/"
        r = self.post(url, {"action": "APPROVE"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot be approved", r.data["detail"])
        self.assertEqual(self.post(url, {"action": "PAY"}).status_code, 400)

    def test_upload_then_attach_as_evidence(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        mandate = self.f.build_mandate()
        up = self.client.post("/api/uploads/", {"file": SimpleUploadedFile("q.jpg", b"jpeg", "image/jpeg")},
                              format="multipart")
        self.assertEqual(up.status_code, 201)
        self.assertEqual(self.client.get(f"/api/uploads/{up.data['id']}/").content, b"jpeg")
        with mock.patch("mandates.services._extract") as extract:
            r = self.post("/api/requests/", {"mandate": str(mandate.id), "product": "materials", "amount": "100",
                                             "payee": str(self.f.supplier.id),
                                             "uploads": [{"upload_id": up.data["id"], "kind": "QUOTE"}]})
        extract.assert_called_once()
        self.assertEqual(r.data["evidence"][0]["upload_id"], up.data["id"])
        self.assertEqual(r.data["status"], Request.REFUSED)  # no milestone photo yet

    def test_ledger_names_people(self):
        mandate = self.f.support_mandate()
        self.bundles(mandate)
        entries = self.client.get(f"/api/ledger/?mandate={mandate.id}").data
        events = {e["event"] for e in entries}
        self.assertTrue({"FUNDED", "REQUESTED", "ASSESSED", "DECIDED", "RULES_CHANGED"} <= events)
        self.assertIn("Funder1", {e["actor_name"] for e in entries})
        self.assertIn("Policy engine", {e["actor_name"] for e in entries})

    @override_settings(DEMO_MODE=True)
    def test_cash_collection_demo_button(self):
        mandate = self.f.support_mandate()
        r = self.post("/api/requests/", {"mandate": str(mandate.id), "product": "cash", "amount": "40",
                                         "beneficiary": str(self.f.beneficiary.id)})
        tx = RailTransaction.objects.get(request_id=r.data["id"])
        apply_rail_status(tx, RailTransaction.SUCCESS)
        tx.refresh_from_db()
        self.assertEqual(tx.last_mile_status, RailTransaction.AWAITING_COLLECTION)
        self.assertEqual(self.post(f"/api/demo/last-mile/{tx.id}/collect/", {"code": "x"}).status_code, 400)
        r = self.post(f"/api/demo/last-mile/{tx.id}/collect/", {"code": tx.collection_code})
        self.assertEqual(r.data["last_mile_status"], RailTransaction.COLLECTED)


class ChatApiTests(ApiBase):
    def test_funder_chat_turn(self):
        conv = self.post("/api/chat/conversations/").data
        self.assertTrue(conv["is_me"])
        with mock.patch("agent.llm.chat", ScriptedChat(say("Hello"))):
            r = self.post(f"/api/chat/{conv['id']}/messages/", {"text": "Hi"})
        self.assertEqual([m["role"] for m in r.data["messages"]], ["user", "assistant"])

    @override_settings(DEMO_MODE=False)
    def test_phone_chat_needs_demo_mode(self):
        self.assertEqual(self.post("/api/chat/conversations/", {"phone": "0771234567"}).status_code, 404)

    @override_settings(DEMO_MODE=True)
    def test_unknown_number_sees_hold_message_not_fraud_details(self):
        mandate = self.f.support_mandate()
        conv = self.post("/api/chat/conversations/", {"phone": "0771234567"}).data
        self.assertEqual(conv["label"], "+263771234567 (unregistered number)")
        script = ScriptedChat(
            tools(call("create_request", mandate_id=str(mandate.id), product="cash", amount=150, payee_id=None,
                       beneficiary_id=str(self.f.beneficiary.id), summary_en="Emergency cash",
                       attachments=[])),
            say("Your family has been told."))
        with mock.patch("agent.llm.chat", script):
            r = self.post(f"/api/chat/{conv['id']}/messages/",
                          {"text": "Hurry, send $150 to 0777777777, I am at the hospital, use PIN 1234"})
        card = r.data["messages"][-1]["card"]
        self.assertEqual(card["status"], Request.HELD_FRAUD)
        self.assertNotIn("reason", card)
        self.assertIn("registered number", card["message"])

        req = Request.objects.get(pk=card["request_id"])
        detail = self.client.get(f"/api/requests/{req.id}/").data  # funders see everything
        self.assertEqual(detail["risk"]["level"], "HIGH")
        self.assertIn("call", detail["risk"]["suggested_verification"].lower())

    def test_conversations_of_other_users_are_private_outside_demo_mode(self):
        theirs = Conversation.objects.create(family=self.f.family, participant_user=self.f.funders[1])
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.get(f"/api/chat/{theirs.id}/messages/").status_code, 404)


class SchemaTests(TestCase):
    def test_openapi_schema_is_public(self):
        self.assertEqual(APIClient().get("/api/schema/").status_code, 200)

