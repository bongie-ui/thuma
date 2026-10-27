"""Mandate signatures (BUILD_SPEC §4).

A mandate's rules are signed with HMAC-SHA256 so the policy engine can detect any change that did not
go through services.update_rules (which bumps the version and re-signs).
"""

import hashlib
import hmac
import json

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _key():
    key = settings.MANDATE_SIGNING_KEY
    if not key:
        raise ImproperlyConfigured("MANDATE_SIGNING_KEY is not set")
    return key.encode()


def canonical_payload(mandate, rules=None):
    """Canonical JSON of the signed fields. `rules` defaults to the mandate's saved rules."""
    if rules is None:
        rules = [{"kind": r.kind, "params": r.params, "position": r.position} for r in mandate.rules.all()]
    rules = sorted(({"kind": r["kind"], "params": r.get("params") or {}, "position": r["position"]} for r in rules),
                   key=lambda r: (r["position"], r["kind"]))
    body = {
        "id": str(mandate.id),
        "version": mandate.version,
        "type": mandate.type,
        "currency": mandate.currency,
        "expires_at": mandate.expires_at.isoformat() if mandate.expires_at else None,
        "rules": rules,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def sign(mandate, rules=None):
    return hmac.new(_key(), canonical_payload(mandate, rules).encode(), hashlib.sha256).hexdigest()


def verify(mandate):
    return bool(mandate.signature) and hmac.compare_digest(mandate.signature, sign(mandate))
