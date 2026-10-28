import json
import tempfile
from pathlib import Path
from unittest import mock

import openai
from django.test import SimpleTestCase, override_settings

from agent import demo_replay, llm

CONFIGURED = dict(OPENAI_API_KEY="sk-test", OPENAI_MODEL="main-model", OPENAI_MODEL_FAST="fast-model")


def completion(content):
    message = mock.Mock(content=content, tool_calls=None)
    return mock.Mock(choices=[mock.Mock(message=message)], model="main-model-2026",
                     usage=mock.Mock(prompt_tokens=1, completion_tokens=1))


@override_settings(**CONFIGURED)
class LLMTests(SimpleTestCase):
    def setUp(self):
        self.client = mock.Mock()
        patcher = mock.patch("agent.llm._get_client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_structured_parses_json(self):
        self.client.chat.completions.create.return_value = completion('{"a": 1}')
        result, model = llm.structured("hi", {"type": "object"}, name="t")
        self.assertEqual(result, {"a": 1})
        self.assertEqual(model, "main-model-2026")
        kwargs = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(kwargs["model"], "main-model")

    def test_fast_model(self):
        self.client.chat.completions.create.return_value = completion("{}")
        llm.structured("hi", {"type": "object"}, name="t", fast=True)
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs["model"], "fast-model")

    @mock.patch("agent.llm.time.sleep")
    def test_retries_then_succeeds(self, sleep):
        timeout = openai.APITimeoutError(request=mock.Mock())
        self.client.chat.completions.create.side_effect = [timeout, timeout, completion("{}")]
        self.assertEqual(llm.structured("hi", {"type": "object"}, name="t")[0], {})
        self.assertEqual(sleep.call_count, 2)

    @mock.patch("agent.llm.time.sleep")
    def test_gives_up_after_two_retries(self, sleep):
        timeout = openai.APITimeoutError(request=mock.Mock())
        self.client.chat.completions.create.side_effect = timeout
        with self.assertRaises(llm.LLMError):
            llm.structured("hi", {"type": "object"}, name="t")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)

    def test_invalid_json(self):
        self.client.chat.completions.create.return_value = completion("not json")
        with self.assertRaises(llm.LLMError):
            llm.structured("hi", {"type": "object"}, name="t")

    def test_images_become_data_urls(self):
        self.client.chat.completions.create.return_value = completion("{}")
        llm.structured("read", {"type": "object"}, name="t", images=[(b"\x89PNG", "image/png")])
        content = self.client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_replay_returns_cached_without_calling(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEMO_REPLAY=True, DEMO_CACHE_DIR=Path(tmp)):
            schema = {"type": "object"}
            key = demo_replay.key_for({"kind": "structured", "model": "main-model",
                                       "messages": [{"role": "user", "content": "hi"}], "schema": schema})
            (Path(tmp) / f"{key}.json").write_text(json.dumps({"result": {"cached": True}, "model": "m"}))
            self.assertEqual(llm.structured("hi", schema, name="t"), ({"cached": True}, "m"))
            self.client.chat.completions.create.assert_not_called()

    @override_settings(OPENAI_API_KEY="")
    def test_not_configured(self):
        with self.assertRaises(llm.LLMError):
            llm.chat([{"role": "user", "content": "hi"}])
