"""The only module that talks to the PayPal REST API. Views and rails call into this."""

import threading
import time

import requests
from django.conf import settings

TIMEOUT_SECONDS = 15
# Refresh the token this many seconds before PayPal says it expires.
EXPIRY_MARGIN_SECONDS = 60


class PayPalError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PayPalClient:
    def __init__(self, client_id=None, client_secret=None, base_url=None):
        self.client_id = client_id if client_id is not None else settings.PAYPAL_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else settings.PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self._token = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self):
        return bool(self.client_id and self.client_secret)

    @property
    def is_sandbox(self):
        return "sandbox" in self.base_url

    def get_access_token(self, force_refresh=False):
        """Return a cached OAuth2 client-credentials token, fetching a new one when needed."""
        if not self.is_configured:
            raise PayPalError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set")
        with self._lock:
            if not force_refresh and self._token and time.time() < self._token_expires_at:
                return self._token
            try:
                resp = requests.post(
                    f"{self.base_url}/v1/oauth2/token",
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json"},
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise PayPalError(f"Could not reach PayPal: {exc}") from exc
            if resp.status_code != 200:
                raise PayPalError("PayPal auth failed", resp.status_code, _safe_json(resp))
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 0) - EXPIRY_MARGIN_SECONDS
            return self._token

    def request(self, method, path, json=None, headers=None):
        """Authenticated JSON request. Retries once with a fresh token on 401."""
        for attempt in range(2):
            token = self.get_access_token(force_refresh=attempt > 0)
            try:
                resp = requests.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        **(headers or {}),
                    },
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise PayPalError(f"Could not reach PayPal: {exc}") from exc
            if resp.status_code == 401 and attempt == 0:
                continue
            if resp.status_code >= 400:
                raise PayPalError(f"PayPal {method} {path} failed", resp.status_code, _safe_json(resp))
            return _safe_json(resp)

    def create_payout(self, receiver_email, amount, currency, reference, note=""):
        """Single-item Payouts batch. `reference` doubles as sender_batch_id, so PayPal rejects duplicates."""
        return self.request("POST", "/v1/payments/payouts", json={
            "sender_batch_header": {
                "sender_batch_id": reference,
                "email_subject": "You have a payment from Thuma",
            },
            "items": [{
                "recipient_type": "EMAIL",
                "receiver": receiver_email,
                "amount": {"value": f"{amount:.2f}", "currency": currency},
                "sender_item_id": reference,
                "note": note,
            }],
        })

    def get_payout_batch(self, payout_batch_id):
        return self.request("GET", f"/v1/payments/payouts/{payout_batch_id}")


def _safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


_client = None


def get_client():
    """Process-wide client so the access token is shared across requests."""
    global _client
    if _client is None:
        _client = PayPalClient()
    return _client
