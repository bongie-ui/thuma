"""Recorded LLM responses so the demo video never depends on a live model call.

Live responses are recorded whenever DEMO_MODE is on; with DEMO_REPLAY on, a recorded response for the
same input hash is returned instead of calling the model.
"""

import hashlib
import json
import logging

from django.conf import settings

log = logging.getLogger(__name__)


def key_for(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _path(key):
    return settings.DEMO_CACHE_DIR / f"{key}.json"


def lookup(key):
    if not settings.DEMO_REPLAY:
        return None
    try:
        return json.loads(_path(key).read_text())
    except (FileNotFoundError, ValueError):
        return None


def store(key, response):
    if not settings.DEMO_MODE or settings.TESTING:
        return
    try:
        settings.DEMO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(json.dumps(response, indent=1, sort_keys=True))
    except OSError as exc:  # read-only disk etc. — recording is best effort
        log.warning("demo replay: could not record %s: %s", key, exc)
