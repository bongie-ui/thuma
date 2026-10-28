"""Render: DEBUG off, secure cookies, required secrets checked at startup."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False  # never read from env/.env in production

for _name in ("DJANGO_SECRET_KEY", "MANDATE_SIGNING_KEY"):
    if not os.environ.get(_name):
        raise ImproperlyConfigured(f"{_name} must be set in production")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 86400
# W008: Render's edge already redirects HTTP to HTTPS; a Django redirect would also hit its health check.
# W005/W021: subdomains of onrender.com are not ours to include or preload.
SILENCED_SYSTEM_CHECKS = ["security.W008", "security.W005", "security.W021"]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]  # noqa: F405

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
