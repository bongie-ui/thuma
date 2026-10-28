# CLAUDE.md — Thuma

Context file for Claude Code. Read this first, then follow **`docs/BUILD_SPEC.md`** (the detailed build plan, data model, phases and acceptance tests). When the two disagree, BUILD_SPEC.md wins on implementation detail; this file wins on product rules.

## What we're building

**Thuma** ("send" in isiNdebele) — purpose-locked diaspora remittances. Family members abroad fund **mandates** (signed rules for how money may be spent). An **AI agent** handles requests from family, suppliers and schools, reads quotes/invoices/photos, flags possible fraud, and proposes payments. A deterministic **policy engine** decides. **PayPal** moves the money.

Built for the **PayPal AI Hackathon** (Devpost). Builder: Bonginkosi, Gwanda, Zimbabwe. Submit by **11 Nov 2026** (deadline 12 Nov, 12:00 PT = 21:00 Harare).

**Elevator pitch:** An AI agent that turns diaspora remittances into purpose-locked payments, paying builders, undertakers and insurers directly, only when the rules you set are met.

**Problem:** Zimbabwe received ~US$2.45bn in remittances in 2025 (RBZ). Money sent for a purpose loses the sender's control once it lands; siblings abroad support the same parent without coordinating; mobile money scams (impersonation, fake emergencies, "send to this number") target exactly these families. Zimbabwean PayPal accounts have historically been send-only, so the last mile is hard.

## Mandate types

| Type | Purpose | Priority |
|---|---|---|
| **Akha** (Build) | Agent checks quotes (price ceiling) + milestone photos, pays the supplier | MUST |
| **Imfundo** (School fees) | Fees locked to a school; paid on the school's invoice | MUST |
| **Isikhwama** (Shared support for a parent) | Several funders share one mandate for airtime, bundles and cash for a registered beneficiary; shared caps; no double top-ups | MUST |
| **Isililo** (Funeral) | Funeral pool (PayPal + local mobile money inbound via Paynow test mode); funeral cover incl. repatriation for members abroad | SHOULD (pool), COULD (cover premiums) |
| **Vikela** (Health) | Local medical aid premiums | COULD |

Mandate types are **rule templates + data**, not separate code paths.

## Fraud flagging (MUST)

Every request is risk-assessed **before** the policy engine:
1. **Deterministic signals** (always run): unregistered sender, a different phone number in the message, beneficiary number recently changed, amount spike, velocity, odd hours, PIN/OTP mentioned.
2. **LLM intent analysis**: stated intent, flags (urgency pressure, impersonation, third-party payment, emergency story, credential request, reversal scam, prize scam, style mismatch, purpose mismatch) with reasons and quotes, plus a suggested verification step.

HIGH risk → **HOLD_FRAUD**: funders must call the beneficiary on the **registered** number and confirm, or report fraud. MEDIUM → escalate to a funder. **AI can only add risk, never remove it.** Details in BUILD_SPEC §7.

## Core rules — never break these

1. **The AI proposes, code decides, PayPal moves the money.** No LLM tool can pay, approve, change rules or change beneficiaries.
2. **AI can only make things stricter.**
3. **Nothing about the demo family is hard-coded.** The Fuyana family exists only in `seed_demo`. Code, prompts and UI are generic; tests use generic data.
4. **PayPal is central in every flow.** All funding via PayPal; all real payouts are PayPal Payouts. Simulated rails are labelled "Simulated rail" in the UI.
5. **Consult the APIMatic Context Plugin** before writing or changing PayPal code.
6. **No third-party brand names/logos** in UI or video. Use neutral labels.

## Money rails

| Rail | Status |
|---|---|
| PayPal Orders (funding) via APIMatic-generated PayPal Server SDK | REAL (sandbox) |
| PayPal Payouts to suppliers, schools, the Local Mobile Money provider account | REAL (sandbox) |
| Local mobile money last mile (airtime/bundles to the beneficiary's number, cash with a collection code) | SIMULATED |
| Biller (funeral cover, medical aid premiums) | SIMULATED |
| Paynow test mode (local contributions, inbound) | REAL test mode |

## Stack & resources

- Backend: Django + DRF, SQLite locally, PostgreSQL on Render, drf-spectacular for OpenAPI.
- Frontend: React + Vite + TypeScript, served by Django (WhiteNoise) on one Render service.
- AI: **OpenAI** (paid key). All calls through `agent/llm.py` (retries, timeouts, demo replay cache). Models from env.
- PayPal: Server SDK (Orders), Payouts REST, Webhooks, JS SDK v6 (fallback v5), Subscriptions/Agent Toolkit if time allows.
- APIMatic: Context Plugin while coding + PayPal Server SDK in code. Keep screenshots for Devpost.
- Render (hosting + webhooks), AG Studio (dashboard + Studio Agent Framework), Postman (public collection), GitHub Actions (tests).
- Cut: Bryntum, voice, dispute auto-response, Astropods, Elastic, Zapier, KERNEL, Channel3.

## Demo cast (seed_demo only)

Sandbox accounts are all US PayPal accounts; story locations differ.

| Name | Kind | Story |
|---|---|---|
| Thuma Platform (`platform@thuma.com`) | PayPal business | Our app; `thuma-platform` app credentials; sends all payouts |
| Mmeli Fuyana | PayPal personal | Son in Johannesburg |
| Bonginkosi Fuyana | PayPal personal | Son in the United States |
| Andile Fuyana | PayPal personal | Son in the United Kingdom |
| Gwanda Hardware | PayPal business | Supplier, Gwanda |
| Sunrise Academy | PayPal business | School, Gwanda |
| Local Mobile Money | PayPal business + simulated last mile | Mobile money provider, Zimbabwe |
| Mama Siqile Fuyana | Beneficiary (no PayPal) | Mother in Gwanda |
| Peaceful Rest Funeral Cover, Imbali Health Medical Aid | Simulated billers | Zimbabwe |

## Coding conventions

- PayPal code only in `payments/` (`paypal_client.py` + `rails/`); never from views.
- Every payout goes through the policy engine and the `Rail` interface; idempotent (`sender_batch_id = thuma-<request id>`).
- Every state change writes an append-only `LedgerEntry`.
- Small, testable functions. Tests first for policy and fraud. `python manage.py test` passes before every commit.
- Never commit `.env`, sandbox passwords or real personal data.

## Working method for Claude Code

- One phase from BUILD_SPEC §18 per session. Read the phase, plan, build, test, then summarise what changed.
- Ask before adding dependencies not listed in BUILD_SPEC.
- After each phase: update "Current status" below.

## Current status

- [x] Skeleton, PayPal OAuth client, `/api/health/paypal/` connected
- [x] Sandbox accounts created; `thuma-platform` linked to platform@thuma.com (~10,000 USD)
- [x] LLM chosen: OpenAI
- [ ] Test payouts verified (hardware, school, mobile money)
- [ ] OpenAI smoke test (isiNdebele + handwritten quote)
- [ ] APIMatic Context Plugin installed
- [x] Phase 1 — Foundations (models, signing, templates) — 27 Oct
  - Settings split: `thuma/settings/{base,local,production}.py` (manage.py → local, wsgi/asgi → production; production refuses to start without `DJANGO_SECRET_KEY` + `MANDATE_SIGNING_KEY`)
  - Apps: `core` (BaseModel UUID+timestamps, `phones.py` E.164 + number finder, `testing.py` generic fixtures), `accounts` (Family, Membership); all §4 models + `BlockedPhone`; admin for all; `LedgerEntry` append-only
  - `mandates/templates.py` replaced `types.py` (rule param specs, required rules per type, `validate_rules`); `mandates/signing.py` HMAC-SHA256
  - `mandates/services.py`: create/sign mandate, `update_rules` (owner only, version bump, re-sign), funding + idempotent capture, balance, contributions, beneficiaries
- [x] Phase 2 — Policy engine + fraud signals + tests — 27 Oct (88 tests passing)
  - `agent/fraud.py` Layer 1 signals (+ `BLOCKED_NUMBER`), injectable Layer 2 analyzer (default = unavailable → `AI_UNAVAILABLE` +10 until Phase 5), AI only adds risk, verification step always uses the registered number
  - `agent/policy.py` all 11 rule kinds; HIGH risk → HOLD_FRAUD *before* hard rules (spec §6 updated); funder approval re-checks hard rules
  - services: `submit_request`, `reassess`, `execute_decision`, `apply_approval`, `inbox`; `payments/payouts.py` idempotent `pay_request` (`thuma-<request id>`) + `apply_rail_status`; `rails.for_payee`
  - `.github/workflows/tests.yml` runs tests + migration check on push
  - Open: `LOCAL_MOBILE_MONEY` still routes to the simulated rail; Phase 4 swaps in the real Payout + last mile. Your `.env` still has `LLM_API_KEY`; rename to `OPENAI_API_KEY` and add `MANDATE_SIGNING_KEY` (see `.env.example`)
- [x] Phase 3 — Render deploy — 28 Oct: live on Render, `/api/health/paypal/` returns connected (sandbox, api-m); repo github.com/bongie-ui/thuma, CI green
  - `render.yaml` (web + Postgres, Frankfurt, free), `build.sh` (pip, frontend if present, collectstatic, migrate), `/api/health/` liveness (DB only) used as Render health check
  - Production: `DEBUG = False` hard-coded, HSTS, secure cookies; `check --deploy` clean; gunicorn + WhiteNoise rehearsed locally
  - Render free tier: web sleeps after 15 min (~1 min wake); no persistent disk (evidence uploads lost on redeploy — store in DB/object storage before Phase 5); **free Postgres expires 30 days after creation → upgrade before ~29 Nov** so it survives judging (1–15 Dec)
- [ ] Phase 4 — PayPal funding, payouts, mobile money rail, webhooks — in progress (97 tests)
  - Done (no PayPal API code): `payments/last_mile.py` simulated last mile (bundles/airtime DELIVERING→DELIVERED after 3s; cash AWAITING_COLLECTION + 6-digit code + beneficiary chat notice → COLLECTED), started on payout SUCCESS; `manage.py poll_payouts [--watch]`
  - **Blocked on APIMatic Context Plugin (rule 5):** Orders create/capture via `paypal-server-sdk`, `LocalMobileMoneyRail` (real Payout to provider with `{beneficiary_phone, product, thuma_request_id}` note), webhooks (`/api/webhooks/paypal`, signature verification, dedupe), fund/capture + demo collect endpoints; then a real sandbox payout via a Request and a webhook received on Render
- [ ] Phase 5 — Agent (drafting, extraction, fraud AI, chat)
- [ ] Phase 6 — Frontend + seed_demo
- [ ] Phase 7 — AG Studio dashboard (+ Isililo, Postman)
- [ ] Phase 8 — Feature freeze, hardening, README
- [ ] Phase 9 — Video + Devpost text
- [ ] Phase 10 — Submitted
