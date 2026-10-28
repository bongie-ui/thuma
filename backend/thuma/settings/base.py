"""Shared Django settings for Thuma. All secrets and environment-specific values come from env vars.

local.py (manage.py default) and production.py (wsgi/asgi default) build on this file.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# .env lives at the repo root (one level above backend/).
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


# `or` so an empty value copied from .env.example falls back to the default.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "dev-insecure-key-change-me"
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
    "accounts",
    "mandates",
    "payments",
    "agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "thuma.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "thuma.wsgi.application"

# SQLite locally; Render provides DATABASE_URL for PostgreSQL.
DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Harare"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"  # evidence files (quotes, milestone photos, invoices)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"  # Thuma models use UUIDs via core.models.BaseModel

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# PayPal — always the sandbox unless explicitly overridden.
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_BASE_URL = os.environ.get("PAYPAL_BASE_URL") or "https://api-m.sandbox.paypal.com"
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")

# HMAC key for mandate signatures (mandates/signing.py). production.py refuses to start without it.
MANDATE_SIGNING_KEY = os.environ.get("MANDATE_SIGNING_KEY", "")

# Country code used to normalise local phone numbers (e.g. 0771234567) to E.164.
DEFAULT_PHONE_COUNTRY_CODE = os.environ.get("DEFAULT_PHONE_COUNTRY_CODE") or "263"

DEMO_MODE = env_bool("DEMO_MODE", False)
DEMO_REPLAY = env_bool("DEMO_REPLAY", False)

TESTING = sys.argv[1:2] == ["test"]

# OpenAI (agent/llm.py is the only consumer). Tests never call the real API.
OPENAI_API_KEY = "" if TESTING else os.environ.get("OPENAI_API_KEY", "")
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS") or 60)
# Recorded LLM responses for DEMO_REPLAY (agent/demo_replay.py).
DEMO_CACHE_DIR = BASE_DIR / "demo_cache"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "")
OPENAI_MODEL_FAST = os.environ.get("OPENAI_MODEL_FAST", "")
