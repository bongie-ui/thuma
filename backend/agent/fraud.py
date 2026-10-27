"""Fraud & risk assessment (BUILD_SPEC §7). Runs on every request before the policy engine.

Layer 1: deterministic signals (always run, cannot be skipped).
Layer 2: LLM intent analysis via an injectable analyzer. It can only ADD risk, never remove it.
"""

import re
import statistics
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from accounts.models import Membership
from core.phones import find_phones, normalize_phone
from mandates.models import Beneficiary, BlockedPhone, Request, RiskAssessment

SIGNAL_WEIGHTS = {
    "UNREGISTERED_SENDER": 35,
    "PAYEE_NUMBER_IN_MESSAGE": 30,
    "BENEFICIARY_RECENTLY_CHANGED": 25,
    "AMOUNT_SPIKE": 20,
    "VELOCITY": 15,
    "ODD_HOURS": 5,
    "CREDENTIALS_MENTIONED": 40,
    "BLOCKED_NUMBER": 60,  # a number previously reported as fraud by this family
    "AI_UNAVAILABLE": 10,
}

AI_FLAGS = ("URGENCY_PRESSURE", "IMPERSONATION", "THIRD_PARTY_PAYMENT", "EMERGENCY_STORY", "CREDENTIAL_REQUEST",
            "REVERSAL_SCAM", "PRIZE_SCAM", "STYLE_MISMATCH", "PURPOSE_MISMATCH", "OTHER")

HIGH_THRESHOLD = 60
MEDIUM_THRESHOLD = 30
PHONE_CHANGE_WINDOW = timedelta(hours=72)
VELOCITY_WINDOW = timedelta(hours=24)
VELOCITY_COUNT = 3
SPIKE_MULTIPLIER = 3
SPIKE_HISTORY = 10
SPIKE_MIN_HISTORY = 3
ODD_HOURS = range(0, 5)  # 00:00–04:59 beneficiary local time

_CREDENTIALS_RE = re.compile(r"\b(pin|otp|one[- ]time|passcode|password|code)\b", re.IGNORECASE)


class AIUnavailable(Exception):
    pass


def no_intent_analyzer(context):
    """Default until the LLM analyzer is wired in (Phase 5): treated as an AI outage."""
    raise AIUnavailable("intent analysis not configured")


def level_for(score):
    if score >= HIGH_THRESHOLD:
        return RiskAssessment.HIGH
    if score >= MEDIUM_THRESHOLD:
        return RiskAssessment.MEDIUM
    return RiskAssessment.LOW


def registered_phones(family):
    phones = set(Beneficiary.objects.filter(family=family).values_list("phone", flat=True))
    phones |= set(Membership.objects.filter(family=family).exclude(phone="").values_list("phone", flat=True))
    return phones


# --- Layer 1 ----------------------------------------------------------------------------------------------

def deterministic_signals(request, now=None):
    """[{signal, weight, detail}] for one request. Pure reads; no writes."""
    now = now or timezone.now()
    family = request.mandate.family
    beneficiary = request.beneficiary
    registered = registered_phones(family)
    signals = []

    def add(name, detail):
        signals.append({"signal": name, "weight": SIGNAL_WEIGHTS[name], "detail": detail})

    sender = normalize_phone(request.requester_phone) if request.requester_phone else None
    if sender and sender not in registered:
        add("UNREGISTERED_SENDER", f"The request came from {sender}, which is not a registered number")

    mentioned = find_phones(request.message_text)
    expected = {beneficiary.phone} if beneficiary else registered
    if others := [p for p in mentioned if p not in expected]:
        add("PAYEE_NUMBER_IN_MESSAGE", f"The message asks to use {', '.join(others)}, not the registered number")

    blocked = set(BlockedPhone.objects.filter(family=family).values_list("phone", flat=True))
    if hits := sorted(blocked & ({sender} | set(mentioned))):
        add("BLOCKED_NUMBER", f"{', '.join(hits)} was reported as fraud before")

    if beneficiary and beneficiary.phone_changed_at and now - beneficiary.phone_changed_at < PHONE_CHANGE_WINDOW:
        add("BENEFICIARY_RECENTLY_CHANGED", "The beneficiary's registered number changed in the last 72 hours")

    if beneficiary:
        history = list(Request.objects.filter(beneficiary=beneficiary, status=Request.PAID)
                       .exclude(pk=request.pk).order_by("-created_at")
                       .values_list("amount", flat=True)[:SPIKE_HISTORY])
        if len(history) >= SPIKE_MIN_HISTORY:
            median = Decimal(statistics.median(history))
            if request.amount > SPIKE_MULTIPLIER * median:
                add("AMOUNT_SPIKE", f"{request.amount} is more than {SPIKE_MULTIPLIER}× the usual {median:.2f}")

        recent = Request.objects.filter(beneficiary=beneficiary, created_at__gte=now - VELOCITY_WINDOW) \
            .exclude(pk=request.pk).count() + 1
        if recent >= VELOCITY_COUNT:
            add("VELOCITY", f"{recent} requests for this beneficiary in the last 24 hours")

        local = now.astimezone(ZoneInfo(beneficiary.timezone))
        if local.hour in ODD_HOURS:
            add("ODD_HOURS", f"Sent at {local:%H:%M} the beneficiary's local time")

    if match := _CREDENTIALS_RE.search(request.message_text or ""):
        add("CREDENTIALS_MENTIONED", f"The message mentions \"{match.group()}\"")

    return signals


# --- Layer 2 ----------------------------------------------------------------------------------------------

def intent_context(request):
    """Inputs for the LLM analyzer (BUILD_SPEC §7)."""
    sender = normalize_phone(request.requester_phone) if request.requester_phone else None
    registered = request.requester_user_id is not None or (sender in registered_phones(request.mandate.family))
    previous = []
    if request.beneficiary:
        previous = list(Request.objects.filter(beneficiary=request.beneficiary, requester_phone=request.beneficiary.phone)
                        .exclude(pk=request.pk).exclude(message_text="").order_by("-created_at")
                        .values_list("message_text", flat=True)[:5])
    return {
        "message_text": request.message_text,
        "requester_registered": registered,
        "beneficiary_recent_messages": previous,
        "amount": str(request.amount),
        "currency": request.mandate.currency,
        "product": request.product,
        "mandate_purpose": request.mandate.purpose_text or request.mandate.title,
    }


def clean_ai_output(output):
    """Normalise analyzer output; risk is clamped to 0–100 so it can never subtract."""
    try:
        ai_risk = max(0, min(100, int(output.get("ai_risk", 0))))
    except (TypeError, ValueError):
        ai_risk = 0
    flags = []
    for f in output.get("flags") or []:
        if not isinstance(f, dict):
            continue
        flag = f.get("flag") if f.get("flag") in AI_FLAGS else "OTHER"
        flags.append({"flag": flag, "reason": str(f.get("reason", "")), "quote": str(f.get("quote", ""))})
    return {
        "ai_risk": ai_risk,
        "flags": flags,
        "summary": str(output.get("summary", "")),
        "stated_intent": str(output.get("stated_intent", "")),
        "suggested_verification": str(output.get("suggested_verification", "")),
        "model_name": str(output.get("model_name", "")),
    }


def verification_step(request, ai_suggestion=""):
    """Always: call the REGISTERED number. An AI suggestion is appended only if it names no other number,
    so a scam message can never steer funders to call the scammer."""
    if request.beneficiary:
        step = (f"Call {request.beneficiary.name} on the registered number ({request.beneficiary.phone}) "
                "and confirm they made this request.")
    else:
        step = "Call the beneficiary on their registered number and confirm they made this request."
    registered = registered_phones(request.mandate.family)
    if ai_suggestion and all(p in registered for p in find_phones(ai_suggestion)):
        step += f" {ai_suggestion}"
    return step


def assess(request, intent_analyzer=no_intent_analyzer, now=None):
    """Create (or replace) the RiskAssessment for `request`."""
    signals = deterministic_signals(request, now=now)
    ai = {"ai_risk": 0, "flags": [], "summary": "", "suggested_verification": "", "model_name": ""}
    try:
        ai = clean_ai_output(intent_analyzer(intent_context(request)) or {})
    except Exception as exc:  # any analyzer failure falls back to Layer 1 only
        signals.append({"signal": "AI_UNAVAILABLE", "weight": SIGNAL_WEIGHTS["AI_UNAVAILABLE"],
                        "detail": f"AI analysis unavailable ({type(exc).__name__}); rules-only assessment"})

    score = min(100, sum(s["weight"] for s in signals) + int(ai["ai_risk"] * 0.5))
    level = level_for(score)
    RiskAssessment.objects.filter(request=request).delete()
    return RiskAssessment.objects.create(
        request=request,
        score=score,
        level=level,
        signals=signals,
        ai_flags=ai["flags"],
        ai_summary=ai["summary"],
        suggested_verification=(verification_step(request, ai["suggested_verification"])
                                if level != RiskAssessment.LOW else ""),
        model_name=ai["model_name"],
    )
