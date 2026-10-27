# Thuma

**Purpose-locked diaspora remittances.** An AI agent that turns diaspora remittances into purpose-locked payments, paying builders, undertakers and insurers directly, only when the rules you set are met.

Built for the PayPal AI Hackathon. PayPal (sandbox) is the central rail for every flow. Some supporting rails are **simulated** and are labelled as such in the UI.

> Work in progress. See `CLAUDE.md` for the full design and schedule.

## Run locally

Requirements: Python 3.12+, Node 20+.

```bash
cp .env.example .env          # then fill in PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (sandbox)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Check the PayPal sandbox connection:

```bash
curl http://127.0.0.1:8000/api/health/paypal/
# {"environment":"sandbox","base_url":"https://api-m.sandbox.paypal.com","status":"connected"}
```

Run tests:

```bash
cd backend && .venv/bin/python manage.py test
```

## License

MIT. See [LICENSE](LICENSE).
