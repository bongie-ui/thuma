"""Local development: SQLite, DEBUG on, a fixed dev signing key if none is set."""

from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
MANDATE_SIGNING_KEY = MANDATE_SIGNING_KEY or "dev-only-mandate-signing-key"  # noqa: F405
