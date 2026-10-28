"""The only module that imports openai. Every model call goes through `chat` or `structured`.

Timeouts, 2 retries with backoff, token logging and demo replay live here.
"""

import base64
import json
import logging
import time

from django.conf import settings

from . import demo_replay

log = logging.getLogger(__name__)

RETRIES = 2
BACKOFF_SECONDS = 1.5


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


def is_configured():
    return bool(settings.OPENAI_API_KEY and settings.OPENAI_MODEL)


def model_name(fast=False):
    return (settings.OPENAI_MODEL_FAST if fast else "") or settings.OPENAI_MODEL


_client = None


def _get_client():
    global _client
    if _client is None:
        import openai
        _client = openai.OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS,
                                max_retries=0)
    return _client


def _call(**kwargs):
    import openai
    retryable = (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
                 openai.InternalServerError)
    for attempt in range(RETRIES + 1):
        started = time.monotonic()
        try:
            response = _get_client().chat.completions.create(**kwargs)
        except retryable as exc:
            if attempt == RETRIES:
                raise LLMError(f"model unavailable: {type(exc).__name__}") from exc
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
            continue
        except openai.APIError as exc:
            raise LLMError(f"model error: {type(exc).__name__}: {exc}") from exc
        usage = response.usage
        log.info("llm %s %.1fs tokens in=%s out=%s", kwargs["model"], time.monotonic() - started,
                 getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
        return response


def image_part(data, content_type):
    encoded = base64.b64encode(bytes(data)).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}}


def user_content(text, images=()):
    """Message content: text plus (bytes, content_type) images."""
    if not images:
        return text
    return [{"type": "text", "text": text}, *(image_part(data, ct) for data, ct in images)]


def structured(prompt, schema, *, name, system=None, images=(), fast=False):
    """One call with a strict JSON schema. Returns (parsed dict, model name)."""
    if not is_configured():
        raise LLMError("OpenAI is not configured")
    model = model_name(fast)
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": user_content(prompt, images)}]
    key = demo_replay.key_for({"kind": "structured", "model": model, "messages": messages, "schema": schema})
    if (cached := demo_replay.lookup(key)) is not None:
        return cached["result"], cached["model"]
    response = _call(model=model, messages=messages, response_format={
        "type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}})
    content = response.choices[0].message.content or ""
    try:
        result = json.loads(content)
    except ValueError as exc:
        raise LLMError("model returned invalid JSON") from exc
    demo_replay.store(key, {"result": result, "model": response.model})
    return result, response.model


def chat(messages, tools=None, *, fast=False):
    """One chat turn. Returns {"content", "tool_calls": [{"id", "name", "arguments"}], "model"}."""
    if not is_configured():
        raise LLMError("OpenAI is not configured")
    model = model_name(fast)
    key = demo_replay.key_for({"kind": "chat", "model": model, "messages": messages, "tools": tools})
    if (cached := demo_replay.lookup(key)) is not None:
        return cached
    kwargs = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    message = _call(**kwargs).choices[0].message
    result = {
        "content": message.content or "",
        "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                       for c in (message.tool_calls or [])],
        "model": model,
    }
    demo_replay.store(key, result)
    return result
