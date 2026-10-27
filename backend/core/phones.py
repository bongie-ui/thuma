"""Phone number helpers: normalise to E.164 and find numbers inside free text."""

import re

from django.conf import settings
from django.core.validators import RegexValidator

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
validate_e164 = RegexValidator(E164_RE, "Use international format, e.g. +263770000001")

# Runs of digits with optional spaces/dashes/dots, optionally led by + or (. Long enough to be a phone.
_CANDIDATE_RE = re.compile(r"(?<![\w$])\+?\(?\d[\d\s().-]{6,18}\d(?![\w])")


def normalize_phone(raw, country_code=None):
    """Return E.164 (+<digits>) or None if `raw` does not look like a phone number."""
    if not raw:
        return None
    country_code = country_code or settings.DEFAULT_PHONE_COUNTRY_CODE
    raw = raw.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        number = digits
    elif digits.startswith("00"):
        number = digits[2:]
    elif digits.startswith("0"):
        number = country_code + digits[1:]
    else:
        number = digits
    candidate = f"+{number}"
    return candidate if E164_RE.match(candidate) else None


def find_phones(text, country_code=None):
    """All phone numbers mentioned in `text`, normalised and de-duplicated, in order of appearance."""
    found = []
    for match in _CANDIDATE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) < 9:
            continue
        phone = normalize_phone(match.group(), country_code)
        if phone and phone not in found:
            found.append(phone)
    return found
