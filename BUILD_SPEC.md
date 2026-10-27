# Thuma — Build Spec (docs/BUILD_SPEC.md)

This is the build plan Claude Code follows to finish Thuma for the PayPal AI Hackathon.
Read `CLAUDE.md` first (product, rules, conventions). This file says **what to build, in what order, and how to know it is done.**

Work one phase at a time. At the end of each phase: run all tests, commit, push, and tick the phase in `CLAUDE.md` → Current status.

**Dates:** today 27 Oct 2026. Feature freeze 8 Nov. Submit 11 Nov. Hard deadline 12 Nov 12:00 PT (21:00 Harare).

---

## 0. Non-negotiables

1. **The AI proposes, code decides, PayPal moves the money.** The LLM never has a tool that pays. Payouts are triggered only by the payment service after the policy engine records an `APPROVE` decision (or a funder approves an escalated request).
2. **AI can only make things stricter.** Fraud and risk analysis can hold or escalate a request; it can never approve something the rules refuse.
3. **Nothing about the demo family is hard-coded.** The Fuyana family exists only in `seed_demo`. Code, prompts and UI text use generic terms ("the beneficiary", "the funders").
4. **PayPal is central in every flow.** Every mandate is funded through PayPal; every real payout is a PayPal Payout. Simulated rails are labelled "Simulated rail" in the UI.
5. **Judges must be able to run it:** hosted URL on Render + full local setup in README + demo logins.
6. **No third-party brand names/logos** in UI or video (no mobile network, mobile money or insurer brands). Use "Local mobile money", "Funeral cover provider", "Medical aid".
7. **Consult the APIMatic Context Plugin** before writing or changing PayPal code.

---

## 1. Scope (cut to fit 15 days)

| Priority | Item |
|---|---|
| **MUST** | Families, members, beneficiaries, payees, mandates with signed rules, multi-funder funding via PayPal |
| **MUST** | Policy engine (rules + balance + risk) with full tests |
| **MUST** | **Fraud & risk assessment** on every request (deterministic signals + LLM intent analysis) |
| **MUST** | Rails: PayPal Payouts (real); Local Mobile Money = real PayPal Payout to provider account + simulated last-mile delivery |
| **MUST** | Agent: chat, mandate drafting from plain language, quote/invoice/photo reading (vision), decision explanations |
| **MUST** | Mandate types: **Akha** (build), **Imfundo** (school fees), **Isikhwama** (shared support for a parent: airtime, bundles, cash) |
| **MUST** | Funder approvals inbox (escalations + fraud holds), ledger, webhooks, Render deploy, README, seed_demo |
| **SHOULD** | **Isililo** funeral pool (PayPal contributions + Paynow test-mode inbound), AG Studio dashboard with a custom agent widget, Postman collection |
| **COULD** | Funeral cover / medical aid premiums via PayPal Subscriptions + biller adapter (Vikela), Invoicing via PayPal Agent Toolkit |
| **CUT** | Bryntum Gantt, voice notes, dispute auto-response, APIMatic partner SDK (mention as roadmap only) |

---

## 2. Resources and exactly how each is used

| Resource | Use in Thuma | Where |
|---|---|---|
| **PayPal Orders v2** via APIMatic-generated **PayPal Server SDK (Python, `paypal-server-sdk`)** | Funders fund a mandate (create order → capture) | `payments/paypal_client.py` |
| **PayPal JS SDK v6** | Pay button in the funder web app. If v6 blocks for more than 2 hours, fall back to the v5 Buttons SDK and note it | `frontend/src/components/FundButton.tsx` |
| **PayPal Payouts (REST)** | Pay suppliers, schools, the local mobile money provider | `payments/rails/paypal_payout.py` |
| **PayPal Webhooks** | Capture completed, payout item succeeded/failed/returned. Verify signatures with `/v1/notifications/verify-webhook-signature` | `payments/webhooks.py` |
| **PayPal Subscriptions** (COULD) | Recurring premiums / monthly support | `payments/subscriptions.py` |
| **PayPal Agent Toolkit** (COULD) | Agent reads invoices (list/get) for school and funeral providers. Verify the Python package and its OpenAI Agents SDK integration first; if it doesn't fit, use Invoicing REST directly | `agent/tools/invoices.py` |
| **OpenAI API** (paid key) | Agent chat + tool calling; structured outputs for mandate drafting and document extraction; vision for quotes/photos; fraud intent analysis | `agent/llm.py` (single wrapper) |
| **APIMatic Context Plugin** | Used by Claude Code while writing all PayPal code; evidence screenshots for Devpost | dev workflow |
| **PayPal AI Toolkit** (Claude Code plugin) | Optional best-practice checks while coding | dev workflow |
| **Render** | Hosting: one web service (Django + built React via WhiteNoise) + PostgreSQL. Public URL for webhooks and judges | `render.yaml` |
| **AG Studio (AG Grid)** | Funder dashboard: custom widgets + Studio Agent Framework | `frontend/src/dashboard/` |
| **Postman** | Public collection generated from the OpenAPI schema for judges | `docs/postman/` |
| **Paynow test mode** (SHOULD) | Local relatives contribute to a funeral pool via local mobile money (inbound only) | `payments/rails/paynow_inbound.py` |
| **GitHub** | Public repo, MIT licence visible in About | repo |

AG Studio trial is 45 days: start it on the day Phase 6 starts and ask the AG Grid team on Discord whether a hackathon licence covers judging (1–15 Dec).

---

## 3. Repository layout (target)

```
thuma/
├── backend/
│   ├── thuma/                 settings/ (base.py, local.py, production.py), urls.py, wsgi.py
│   ├── accounts/              User profile, Family, Membership, demo login
│   ├── mandates/              Beneficiary, Payee, Mandate, Rule, Funding, Request, Evidence,
│   │                          RiskAssessment, Decision, Approval, LedgerEntry; services.py; signing.py
│   ├── payments/              paypal_client.py, rails/, webhooks.py, subscriptions.py
│   ├── agent/                 llm.py, prompts/, tools/, chat.py, drafting.py, extraction.py,
│   │                          policy.py, fraud.py, demo_replay.py
│   └── core/management/commands/seed_demo.py
├── frontend/                  React + Vite + TypeScript
├── docs/                      BUILD_SPEC.md, architecture.png, schedule.png, postman/
├── render.yaml
├── .env.example
├── CLAUDE.md
├── LICENSE (MIT)
└── README.md
```

---

## 4. Data model

All models have `id` (UUID), `created_at`, `updated_at`. Money is `DecimalField(max_digits=12, decimal_places=2)`; currency `CharField(3)`, default `USD`.

**accounts**
- `Family`: name, created_by(User)
- `Membership`: user, family, role (`ADMIN` | `FUNDER` | `VIEWER`), paypal_email (sandbox), country, phone
- Users log in with Django auth. Beneficiaries do NOT need user accounts.

**mandates**
- `Beneficiary`: family, name, relationship, phone (E.164), allowed_products (JSON list: `airtime`, `bundles`, `cash`, `school_fees`, …), registered_by(User), verified_at, phone_changed_at (nullable)
- `Payee`: family (nullable = shared registry), name, kind (`SUPPLIER` | `SCHOOL` | `MOBILE_MONEY_PROVIDER` | `FUNERAL_PROVIDER` | `MEDICAL_AID` | `OTHER`), rail (`PAYPAL_PAYOUT` | `LOCAL_MOBILE_MONEY` | `BILLER_SIM`), paypal_email, external_ref, verified (bool)
- `Mandate`: family, type (`AKHA` | `IMFUNDO` | `ISIKHWAMA` | `ISILILO` | `VIKELA`), title, purpose_text (original plain-language request), currency, status (`DRAFT` | `ACTIVE` | `PAUSED` | `CLOSED`), expires_at, version (int), signature (hex), created_by
- `Rule`: mandate, kind, params (JSON), position. Kinds in §5.
- `MandateFunder`: mandate, user, role (`OWNER` | `CO_FUNDER`)
- `Funding`: mandate, funder(User), amount, rail (`PAYPAL` | `PAYNOW_INBOUND`), external_id (PayPal order/capture id), status (`CREATED` | `CAPTURED` | `FAILED`)
- `Request`: mandate, channel (`CHAT` | `APP` | `SCHEDULE`), requester_user (nullable), requester_phone (nullable), requester_display, beneficiary (nullable), payee (nullable), product, amount, message_text, idempotency_key (unique), status (`NEW` | `ASSESSED` | `APPROVED` | `REFUSED` | `ESCALATED` | `HELD_FRAUD` | `PAID` | `FAILED` | `CANCELLED` | `CONFIRMED_FRAUD`)
- `Evidence`: request, kind (`QUOTE` | `INVOICE` | `MILESTONE_PHOTO` | `RECEIPT` | `OTHER`), file, extracted (JSON), model_name
- `RiskAssessment`: request, score (0–100), level (`LOW` | `MEDIUM` | `HIGH`), signals (JSON list of deterministic signals), ai_flags (JSON list `{flag, reason, quote}`), ai_summary, model_name
- `Decision`: request, outcome (`APPROVE` | `REFUSE` | `ESCALATE` | `HOLD_FRAUD`), rule_results (JSON list `{rule_id, kind, passed, detail}`), reason (plain words), decided_by (`POLICY` | user id)
- `Approval`: request, user, action (`APPROVE` | `REJECT` | `VERIFIED_SAFE` | `REPORT_FRAUD`), note
- `RailTransaction`: request, rail, amount, external_id (payout batch/item id), status (`PENDING` | `SUCCESS` | `FAILED` | `RETURNED`), last_mile_status (`N/A` | `DELIVERING` | `DELIVERED` | `AWAITING_COLLECTION` | `COLLECTED`), collection_code (nullable), raw (JSON)
- `LedgerEntry` (append-only, never updated): family, mandate, request (nullable), event (`FUNDED` | `REQUESTED` | `ASSESSED` | `DECIDED` | `APPROVED_BY_FUNDER` | `PAID` | `DELIVERED` | `FAILED` | `FRAUD_HELD` | `FRAUD_CONFIRMED` | `RULES_CHANGED`), amount (nullable), actor, data (JSON)
- `Conversation` / `ChatMessage`: family, participant (user or phone), role (`user` | `assistant` | `system`), text, attachments, linked_request (nullable)
- `WebhookEvent`: paypal_event_id (unique), event_type, payload, processed_at
- `BlockedPhone`: family, phone, reason, request — numbers reported via `REPORT_FRAUD`

Model placement: `accounts` (Family, Membership), `mandates` (everything above except the next two), `payments` (RailTransaction, WebhookEvent), `agent` (Conversation, ChatMessage). `core.models.BaseModel` gives UUID + timestamps. Request statuses `APPROVED` (payout pending) and `PAID` count as committed for balances, caps and intervals.

**Derived values (services, not stored):** mandate balance = captured funding − (paid + pending payouts). Per-funder contribution = sum of that funder's captured funding.

**Signing:** `mandates/signing.py` builds canonical JSON of (mandate id, version, type, rules sorted by position, currency, expiry) and signs it with HMAC-SHA256 using `MANDATE_SIGNING_KEY`. Any rule change bumps the version, re-signs, writes a `RULES_CHANGED` ledger entry, and requires owner confirmation. The policy engine refuses if the signature does not verify.

---

## 5. Rules (data, not code)

| kind | params example | Check |
|---|---|---|
| `allowed_payees` | `{"payee_ids": [...]}` | request.payee in list |
| `allowed_beneficiaries` | `{"beneficiary_ids": [...]}` | request.beneficiary in list |
| `allowed_products` | `{"products": ["airtime","bundles","cash"]}` | request.product in list and in beneficiary.allowed_products |
| `max_per_request` | `{"amount": 600}` | amount ≤ limit |
| `cap_per_period` | `{"amount": 30, "period": "month", "product": "bundles", "shared": true}` | sum of PAID+PENDING for product in period (across all funders if shared) + amount ≤ cap |
| `min_interval` | `{"hours": 24, "product": "bundles"}` | no PAID/PENDING request for same product + beneficiary within window. On fail, detail says who did it and when |
| `requires_evidence` | `{"kind": "MILESTONE_PHOTO", "label": "foundation complete"}` | an Evidence of that kind exists and its `extracted.verdict == "matches"` |
| `price_ceiling` | `{"item": "cement_bag", "max_unit_price": 11.00}` | every extracted line item matching `item` has unit_price ≤ max |
| `requires_invoice` | `{}` | an INVOICE evidence exists and extracted total == amount and payee matches |
| `escalate_above` | `{"amount": 200}` | if amount > limit → outcome ESCALATE (not refuse) |
| `auto_approve_below` | `{"amount": 50}` | above this, ESCALATE even if all rules pass (optional) |

Default rule sets per mandate type live in `mandates/templates.py` (Akha, Imfundo, Isikhwama, Isililo, Vikela). The drafting agent fills params; templates guarantee required rules exist.

---

## 6. Policy engine — `agent/policy.py` (pure, deterministic, heavily tested)

```
evaluate(request) -> Decision
  1. verify mandate signature and status ACTIVE and not expired → else REFUSE
  2. balance check: amount ≤ available balance → else REFUSE ("insufficient mandate funds")
  3. run every rule → rule_results
  4. risk = request.risk_assessment (must exist; created by fraud.assess before policy)
  outcome:
    - risk.level == HIGH → HOLD_FRAUD (before hard rules, so funders always see the fraud card)
    - any hard rule failed (not escalate_above/auto_approve_below) → REFUSE
    - risk.level == MEDIUM → ESCALATE
    - escalate_above or auto_approve_below triggered → ESCALATE
    - else → APPROVE
  5. write Decision + LedgerEntry; set request.status
```

- `services.execute_decision(request)`: if APPROVE → rail router pays. If ESCALATE / HOLD_FRAUD → notify funders (in-app inbox; email optional).
- `services.apply_approval(request, user, action)`:
  - ESCALATE + APPROVE by any funder → pay. REJECT → REFUSED.
  - HOLD_FRAUD requires `VERIFIED_SAFE` with a note confirming the funder called the beneficiary on the **registered** number. Then pay. `REPORT_FRAUD` → CONFIRMED_FRAUD, ledger, and auto-pause payouts to any phone number in the flagged message.
- Hard refusals cannot be overridden by approval (they need a mandate rule change, which is versioned and signed).
- Funder APPROVE / VERIFIED_SAFE re-runs `policy.check(request, funder_verified=True)`: risk and soft rules count as satisfied by the funder, but signature, status, expiry, balance and every hard rule still apply. So a fraud hold that also breaks a rule is REFUSED after verification, never paid.

---

## 7. Fraud & risk assessment — `agent/fraud.py`

Mobile money scams targeting families are common. Typical patterns: someone impersonating a parent from a new number ("I lost my phone, use this number"), fake emergencies (hospital, police, accident, funeral) with urgency, requests to send to a different number or an "agent", requests for PINs/OTPs, "wrong send, please reverse", fake prizes or promotions, SIM-swap takeovers, and amounts far above the usual pattern.

Assessment runs on **every** request before the policy engine, in two layers:

**Layer 1 — deterministic signals (code, always runs, cannot be skipped):**

| signal | weight |
|---|---|
| `UNREGISTERED_SENDER` — requester_phone is not a registered beneficiary/member number | 35 |
| `PAYEE_NUMBER_IN_MESSAGE` — message contains a phone number different from the beneficiary's registered number | 30 |
| `BENEFICIARY_RECENTLY_CHANGED` — beneficiary phone changed < 72h ago | 25 |
| `AMOUNT_SPIKE` — amount > 3× median of this beneficiary's last 10 paid requests (min history 3) | 20 |
| `VELOCITY` — ≥ 3 requests for this beneficiary in 24h | 15 |
| `ODD_HOURS` — request between 00:00 and 05:00 beneficiary local time | 5 |
| `CREDENTIALS_MENTIONED` — message mentions PIN / OTP / code / password | 40 |
| `BLOCKED_NUMBER` — sender or a number in the message was reported as fraud by this family (`BlockedPhone`) | 60 |

**Layer 2 — LLM intent analysis (OpenAI, structured output):** input = message text, requester (registered or not), beneficiary's last 5 messages for style comparison, request amount and product, mandate purpose. Output JSON schema:

```json
{
  "stated_intent": "string — what the requester says the money is for",
  "flags": [{"flag": "URGENCY_PRESSURE|IMPERSONATION|THIRD_PARTY_PAYMENT|EMERGENCY_STORY|CREDENTIAL_REQUEST|REVERSAL_SCAM|PRIZE_SCAM|STYLE_MISMATCH|PURPOSE_MISMATCH|OTHER",
             "reason": "string, plain words for the funders",
             "quote": "short excerpt from the message"}],
  "ai_risk": 0,
  "summary": "one or two sentences for the funders",
  "suggested_verification": "e.g. call the beneficiary on the registered number and ask about X"
}
```

**Scoring:** `score = min(100, sum(signal weights) + ai_risk * 0.5)`. Level: `HIGH` ≥ 60, `MEDIUM` 30–59, `LOW` < 30. If the LLM call fails, use Layer 1 only and add signal `AI_UNAVAILABLE` (+10). The LLM output can only add risk; it never lowers a deterministic signal.

**Suggested verification** always starts with "call the beneficiary on the registered number"; an AI suggestion is appended only if it names no unregistered number (a scam message must never steer funders to call the scammer).

**UI:** the approvals inbox shows a red "Possible fraud" card: score, each flag with its reason and the quoted text, the suggested verification step, and buttons **I called and it's genuine** / **Report fraud**.

**Tests (required):** registered beneficiary routine bundle request → LOW; new-number "hospital, send $150 to 07xx…" → HIGH (deterministic signals alone must reach HIGH, even with the LLM mocked to return 0); PIN mentioned → at least MEDIUM; LLM failure → falls back without crashing.

---

## 8. Rails — `payments/rails/`

```python
class Rail(Protocol):
    name: str
    simulated: bool
    def pay(self, request, payee, amount, reference) -> RailResult: ...
    def status(self, external_id) -> RailResult: ...
```

- `PayPalPayoutRail` (real): Payouts API, `sender_batch_id = f"thuma-{request.id}"` (idempotent), recipient = payee.paypal_email, note = reference. Status updated by webhooks, with polling as a fallback.
- `LocalMobileMoneyRail`: step 1 real PayPal Payout to the provider's PayPal business account (payee kind `MOBILE_MONEY_PROVIDER`), note carries `{beneficiary_phone, product, thuma_request_id}`. Step 2 simulated last mile, triggered when the payout succeeds: airtime/bundles → `DELIVERED` after ~3s; cash → `AWAITING_COLLECTION` with a 6-digit `collection_code` and an SMS-style notice in the beneficiary chat ("You have $40 from your family. Collect at any mobile money agent with code 482193"); a demo button marks it `COLLECTED`.
- `BillerSimRail` (simulated): premiums; succeeds after ~2s with a fake receipt number.
- `PaynowInbound` (SHOULD): Paynow test-mode express checkout for local contributions to an Isililo pool; on success create `Funding(rail=PAYNOW_INBOUND)`.
- Router: `rails.for_payee(payee)` picks by `payee.rail`. Every RailTransaction and status change writes a LedgerEntry.

---

## 9. Agent — `agent/`

- `llm.py`: the only file that imports `openai`. Functions: `chat(messages, tools)`, `structured(prompt, schema, images=None)`. Model names from env (`OPENAI_MODEL`, optional `OPENAI_MODEL_FAST`). Timeouts, 2 retries with backoff, token/cost logging. If `DEMO_REPLAY=true` and a cached response exists for the input hash → return it (`demo_replay.py`, cache in `backend/demo_cache/`).
- `drafting.py`: plain-language purpose → mandate JSON (type, title, rules with params) via structured output, validated against the templates. Shown to the funder for confirmation before saving and signing.
- `extraction.py`: Evidence file → structured JSON. Quote/invoice: `{supplier, items:[{name, quantity, unit_price}], total, currency, date}`. Milestone photo: `{verdict: "matches"|"does_not_match"|"unclear", observed: "...", expected: "..."}`.
- `chat.py`: the conversation endpoint for funders and for beneficiaries/payees (beneficiary chat is identified by phone in demo mode). Tools available to the model:
  - `get_mandates()` — active mandates + balances visible to this participant
  - `get_beneficiaries()`
  - `create_request(mandate_id, product, amount, payee_id?, beneficiary_id?, message_text)` — creates a Request (NOT a payment); the backend then runs fraud.assess → policy.evaluate → execute_decision, and returns the outcome
  - `attach_evidence(request_id, upload_id, kind)` — triggers extraction
  - `get_request_status(request_id)`
  - `explain_decision(request_id)` — returns rule results + risk flags for the model to explain in plain words
  - NO tool can pay, approve, change rules or change beneficiaries.
- Languages: reply in the language the user writes in (English, isiNdebele, Shona); store an English summary on the Request.
- Prompts in `agent/prompts/*.md`, generic, filled at runtime.

---

## 10. API (Django REST Framework) — `/api/`

Auth: session auth + CSRF for the SPA. OpenAPI via `drf-spectacular` at `/api/schema/` and Swagger at `/api/docs/`.

- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`; `POST /auth/demo-login` (only when `DEMO_MODE=true`: pick a seeded user)
- `GET/POST /families`, `POST /families/{id}/invite`
- `GET/POST /beneficiaries`, `PATCH /beneficiaries/{id}`
- `GET/POST /payees`
- `POST /mandates/draft` (plain text → proposed mandate JSON), `POST /mandates` (confirm + sign), `GET /mandates`, `GET /mandates/{id}`, `POST /mandates/{id}/funders`
- `POST /mandates/{id}/fund/create-order` → PayPal order id; `POST /mandates/{id}/fund/capture`
- `POST /requests` (app channel), `GET /requests?status=`, `GET /requests/{id}` (with evidence, risk, decision, rail tx)
- `POST /requests/{id}/approval` (`APPROVE` | `REJECT` | `VERIFIED_SAFE` | `REPORT_FRAUD`)
- `POST /uploads` (image/pdf) → upload id
- `POST /chat/{conversation_id}/messages`, `GET /chat/{conversation_id}/messages`
- `GET /ledger?mandate=&family=`
- `GET /dashboard/summary` (aggregates for AG Studio)
- `POST /webhooks/paypal` (no auth; signature verified)
- `POST /demo/last-mile/{rail_tx_id}/collect` (demo mode only)
- `GET /health/paypal` (exists)

---

## 11. Frontend — React + Vite + TypeScript

Single app, role-based. Clean, mobile-friendly. Every simulated rail shows a small "Simulated rail" tag.

Screens:
1. **Login** + demo user switcher (demo mode only), showing which persona you are.
2. **Home**: family mandates as cards (type, balance, funders' contributions, status) + "New mandate".
3. **New mandate**: textarea ("Up to $600 for cement and bricks for the house in Gwanda, pay the hardware store directly after the foundation photo") → AI draft shown as readable rules → edit → confirm & sign.
4. **Mandate detail**: rules in plain words, funders + contributions, **Fund with PayPal** button, requests list, ledger timeline.
5. **Beneficiaries & payees**: register a beneficiary (name, phone, allowed products); changing a phone shows a warning that it triggers fraud checks for 72h.
6. **Approvals inbox**: escalations and fraud holds; fraud card as in §7.
7. **Chat**: funder chat and beneficiary/payee chat (mobile layout, photo upload, decision cards inline: approved / refused with reasons / held for verification).
8. **Quick actions** (Isikhwama): "Buy airtime", "Buy bundles", "Send cash" for a beneficiary, showing what's already been covered this period and by whom.
9. **Dashboard** (AG Studio, Phase 6).

Serve the built SPA from Django (WhiteNoise) so Render runs one web service.

---

## 12. Webhooks

Subscribe the sandbox app (on the Render URL) to: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `PAYMENT.PAYOUTS-ITEM.FAILED`, `PAYMENT.PAYOUTS-ITEM.RETURNED`, `PAYMENT.PAYOUTSBATCH.SUCCESS` (plus `BILLING.SUBSCRIPTION.*` if Vikela is built). Store each in `WebhookEvent` (dedupe by event id), verify the signature using `PAYPAL_WEBHOOK_ID`, process idempotently, and write a ledger entry. Locally, a management command `poll_payouts` updates pending RailTransactions so development works without a public URL.

---

## 13. Seed data — `python manage.py seed_demo [--reset]`

Creates, **through the services** (not raw inserts), the demo family:
- Family "Fuyana family"; members Mmeli (ZA story), Bonginkosi (US story), Andile (UK story) with their sandbox PayPal emails from `.env` (`DEMO_FUNDER_*_EMAIL`), password from `DEMO_PASSWORD`
- Beneficiary Mama Siqile Fuyana (+263 77 000 0001 — fake), products airtime/bundles/cash
- Payees: Gwanda Hardware (SUPPLIER, PayPal), Sunrise Academy (SCHOOL, PayPal), Local Mobile Money (MOBILE_MONEY_PROVIDER, LOCAL_MOBILE_MONEY rail), Peaceful Rest Funeral Cover + Imbali Health Medical Aid (BILLER_SIM)
- Mandates: Akha ($600, price ceiling $11/bag cement, foundation photo required), Imfundo (term fees, Sunrise Academy, invoice required), Isikhwama (shared by all three; bundles $30/month shared, min interval 24h; airtime $20/month; cash $100/month, escalate above $50)
- Fundings marked CAPTURED with fake ids for history (live funding in the demo uses real sandbox checkout)
- A few historical paid requests so AMOUNT_SPIKE has a baseline
- Sample files in `backend/demo_assets/` (handwritten quote at $14/bag, foundation photo, school invoice)

---

## 14. Demo scenarios (acceptance tests for the whole product)

1. **Inflated quote refused:** builder chat uploads a quote at $14/bag → extraction → `price_ceiling` fails → REFUSE with the plain-words reason; agent suggests asking for a revised quote; revised $10.50 quote + foundation photo → APPROVE → real PayPal payout to Gwanda Hardware.
2. **School fees:** invoice from Sunrise Academy → `requires_invoice` passes → APPROVE → payout to the school.
3. **Shared support, no double top-up:** Andile buys bundles for Mama → payout to Local Mobile Money → "Delivered". Mmeli tries an hour later → `min_interval` fails → refusal explaining Andile covered it today, suggesting airtime instead.
4. **Fraud caught:** an unregistered number messages "Mwanami, I'm at the hospital, please send $150 to 0771234567, the agent will help me, hurry" → signals UNREGISTERED_SENDER + PAYEE_NUMBER_IN_MESSAGE + AMOUNT_SPIKE, AI flags URGENCY_PRESSURE / IMPERSONATION / THIRD_PARTY_PAYMENT → HIGH → HOLD_FRAUD → all funders see the red card with "call Mama on her registered number" → Mmeli reports fraud → CONFIRMED_FRAUD, number blocked.
5. **Cash for Mama:** Bonginkosi sends $40 cash → payout → "Awaiting collection, code 482193" → mark collected.
6. **(SHOULD) Funeral pool:** pool funded by PayPal from the sons + Paynow test-mode contribution from a local relative.

Each scenario must work on the Render URL with demo logins, and must also have an automated backend test (PayPal and OpenAI mocked).

---

## 15. Tests (minimum)

- Policy: each rule kind pass/fail; shared cap across funders; min_interval names the other funder; signature tamper → REFUSE; balance check; hard refusal not overridable.
- Fraud: the four tests in §7.
- Rails: payout idempotency (same request → same sender_batch_id, no double pay); last-mile state machine; webhook dedupe.
- Agent: tools cannot pay (assert tool list); drafting output validates against templates; extraction parsing with a mocked LLM.
- Scenarios 1–5 end-to-end with mocks.
- `python manage.py test` must pass before every commit. Add a GitHub Actions workflow running the tests on push.

---

## 16. Environment variables (`.env.example`)

```
DJANGO_SECRET_KEY=
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=                      # empty locally → SQLite
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=
VITE_PAYPAL_CLIENT_ID=             # same sandbox client id, public
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_MODEL_FAST=
MANDATE_SIGNING_KEY=
DEMO_MODE=true
DEMO_REPLAY=false
DEMO_PASSWORD=
DEMO_FUNDER_1_EMAIL=
DEMO_FUNDER_2_EMAIL=
DEMO_FUNDER_3_EMAIL=
PAYNOW_INTEGRATION_ID=
PAYNOW_INTEGRATION_KEY=
PAYNOW_AUTH_EMAIL=
```

---

## 17. Deployment — Render

- `render.yaml` blueprint: one web service (build: install Python deps, `npm ci && npm run build` in frontend, `collectstatic`, `migrate`; start: `gunicorn thuma.wsgi`), one PostgreSQL database.
- Production settings: `DEBUG=False`, WhiteNoise, `dj-database-url`, secure cookies, `CSRF_TRUSTED_ORIGINS` with the Render URL.
- After the first deploy: run `seed_demo`, register the webhook URL `https://<app>.onrender.com/api/webhooks/paypal` in the PayPal dashboard, and put the webhook id in Render env.
- Check Render's current free-tier limits (sleeping services, database expiry). Before 1 Dec, make sure the service and database will stay up through judging (15 Dec).

---

## 18. Phases (execute in order)

Each phase: build → tests pass → manual check → commit + push → tick in CLAUDE.md.

| # | Dates | Phase | Done when |
|---|---|---|---|
| 1 | 28 Oct | Foundations: settings split, accounts app, all models + migrations, signing, templates, admin registration | migrations apply; admin shows all models; signing tests pass |
| 2 | 28–29 Oct | Policy engine + fraud Layer 1 + services + full tests | §15 policy and fraud deterministic tests pass |
| 3 | 30 Oct | Render deploy (early!): render.yaml, production settings, Postgres, health check live | `https://<app>.onrender.com/api/health/paypal` returns connected |
| 4 | 30–31 Oct | PayPal: Server SDK orders (fund/capture), Payout rail, Local Mobile Money rail + last mile, webhooks, poll_payouts, ledger | a real sandbox payout via a Request; webhook received on Render |
| 5 | 1–3 Nov | Agent: llm.py, drafting, extraction (vision), fraud Layer 2, chat + tools, demo replay | scenarios 1–5 pass as backend tests; manual chat test works |
| 6 | 3–6 Nov | Frontend: all screens in §11, PayPal button, approvals inbox, chat, quick actions; seed_demo | scenarios 1–5 work by clicking through on Render |
| 7 | 6–7 Nov | AG Studio dashboard (custom widgets: funds by mandate, per-funder contributions, spend by category, fraud alerts tile, ledger grid; Studio Agent Framework: natural-language widget creation) + SHOULD items (Isililo, Postman) | dashboard live on Render |
| 8 | 8 Nov | **Feature freeze.** Hardening: error states, empty states, loading, mobile check, README, demo logins, Postman collection, GitHub Actions green | a fresh clone runs from the README alone |
| 9 | 9–10 Nov | Video recording (DEMO_REPLAY on for reliability), Devpost text | video under 2:45 on YouTube |
| 10 | 11 Nov | Submit | submitted; links checked in a private window |

If behind: cut in this order → Vikela → Isililo Paynow inbound → AG Studio agent framework (keep basic widgets) → Postman. Never cut the policy engine, fraud hold, scenarios 1–5, Render deploy, or README.

---

## 19. README must contain (judges read this)

1. One-paragraph pitch + problem + who it's for
2. Hosted demo URL + demo logins (each persona) + a "try this in 3 minutes" script (scenarios 3 and 4)
3. Architecture image + "AI proposes, code decides, PayPal moves the money"
4. **Real vs simulated** table (honest)
5. **Tools used**: PayPal (Orders via Server SDK, Payouts, Webhooks, JS SDK, Subscriptions/Agent Toolkit if built), OpenAI (what for), APIMatic Context Plugin + Server SDK, Render, AG Studio, Postman, Paynow test mode
6. Local setup (Mac/Linux and Windows), env vars, `seed_demo`, tests
7. Sandbox test accounts judges can use (sandbox only)
8. Fraud model explanation (signals table + AI flags)
9. Licence (MIT)

---

## 20. Devpost submission checklist

- [ ] Project title, elevator pitch, full description (problem, who, how, what's real vs simulated)
- [ ] "Built with" / tools used with explanations (PayPal products, OpenAI, APIMatic, Render, AG Studio, Postman)
- [ ] Public GitHub repo URL, MIT licence visible in About
- [ ] Hosted demo URL + test credentials
- [ ] YouTube video, public, under 3 minutes, no third-party brands or copyrighted music, shows the product working end-to-end
- [ ] Screenshots / architecture image in the gallery
- [ ] Explanation of what was built during the submission period (all of it — new project)
- [ ] Opted into sponsor prize: AG Grid (primary)
