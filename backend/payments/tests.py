from unittest import mock

from django.test import SimpleTestCase, override_settings

from . import paypal_client
from .paypal_client import PayPalClient, PayPalError


def fake_response(status_code, payload):
    resp = mock.Mock(status_code=status_code)
    resp.json.return_value = payload
    return resp


class PayPalClientTests(SimpleTestCase):
    def make_client(self):
        return PayPalClient("id", "secret", "https://api-m.sandbox.paypal.com")

    @mock.patch("payments.paypal_client.requests.post")
    def test_token_is_cached(self, post):
        post.return_value = fake_response(200, {"access_token": "tok", "expires_in": 32400})
        client = self.make_client()
        self.assertEqual(client.get_access_token(), "tok")
        self.assertEqual(client.get_access_token(), "tok")
        self.assertEqual(post.call_count, 1)

    @mock.patch("payments.paypal_client.requests.post")
    def test_auth_failure_raises(self, post):
        post.return_value = fake_response(401, {"error": "invalid_client"})
        with self.assertRaises(PayPalError) as ctx:
            self.make_client().get_access_token()
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unconfigured_client_raises(self):
        with self.assertRaises(PayPalError):
            PayPalClient("", "", "https://api-m.sandbox.paypal.com").get_access_token()


@override_settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com")
class PayPalHealthViewTests(SimpleTestCase):
    def setUp(self):
        paypal_client._client = None

    def tearDown(self):
        paypal_client._client = None

    @override_settings(PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET="")
    def test_not_configured(self):
        resp = self.client.get("/api/health/paypal/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["status"], "not_configured")

    @override_settings(PAYPAL_CLIENT_ID="id", PAYPAL_CLIENT_SECRET="secret")
    @mock.patch("payments.paypal_client.requests.post")
    def test_connected(self, post):
        post.return_value = fake_response(200, {"access_token": "tok", "expires_in": 32400})
        resp = self.client.get("/api/health/paypal/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "connected")
        self.assertEqual(resp.json()["environment"], "sandbox")
        self.assertNotIn("tok", resp.content.decode())
