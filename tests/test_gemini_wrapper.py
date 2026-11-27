"""Проверка логики GeminiLLM (повторы, разбор JSON) на подставном SDK. Реальный API здесь не вызывается."""
import sys
import types
import unittest
from unittest import mock


def fake_sdk(responses):
    """responses: список строк или исключений, выдаваемых по очереди."""
    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append((model, contents, config))
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return types.SimpleNamespace(text=r)

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
    google = types.ModuleType("google")
    google.genai = genai
    return {"google": google, "google.genai": genai, "google.genai.types": genai.types}, calls


class GeminiWrapper(unittest.TestCase):
    def make(self, responses):
        mods, calls = fake_sdk(responses)
        with mock.patch.dict(sys.modules, mods), mock.patch("time.sleep"):
            from validator.llm import GeminiLLM

            llm = GeminiLLM("key", "model-x", min_interval=0, retries=3)
            return llm, calls

    def test_retries_after_error_then_parses_fenced_json(self):
        llm, calls = self.make([RuntimeError("429"), '```json\n{"ok": true}\n```'])
        with mock.patch("time.sleep"):
            self.assertEqual(llm.complete_json("s", "sys", "p"), {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2]["temperature"], 0.0)
        self.assertEqual(calls[0][2]["response_mime_type"], "application/json")
        self.assertEqual(calls[0][0], "model-x")

    def test_invalid_json_gets_one_reminder_then_succeeds(self):
        llm, calls = self.make(["не json", '{"a": 1}'])
        with mock.patch("time.sleep"):
            self.assertEqual(llm.complete_json("s", "sys", "p"), {"a": 1})
        self.assertIn("только валидный JSON", calls[1][1])

    def test_fatal_code_fails_fast_without_retries(self):
        from validator.llm import LLMFatalError

        class NotFound(Exception):
            code = 404

        llm, calls = self.make([NotFound("model gone")] * 3)
        with mock.patch("time.sleep") as sl, self.assertRaises(LLMFatalError) as cm:
            llm.complete_json("s", "sys", "p")
        self.assertEqual(len(calls), 1)
        self.assertIn("GEMINI_MODEL", str(cm.exception))
        sl.assert_not_called()

    def test_invalid_key_error_400_fails_fast_with_hint(self):
        from validator.llm import LLMFatalError

        class BadKey(Exception):
            code = 400

        llm, calls = self.make([BadKey("API key not valid")] * 3)
        with mock.patch("time.sleep"), self.assertRaises(LLMFatalError) as cm:
            llm.complete_json("s", "sys", "p")
        self.assertEqual(len(calls), 1)
        self.assertIn("GEMINI_API_KEY", str(cm.exception))

    def test_daily_quota_stops_immediately(self):
        from validator.llm import LLMQuotaError

        class Quota(Exception):
            code = 429

        llm, calls = self.make([Quota("Quota exceeded ... GenerateRequestsPerDayPerProjectPerModel-FreeTier")] * 5)
        with mock.patch("time.sleep") as sl, self.assertRaises(LLMQuotaError):
            llm.complete_json("s", "sys", "p")
        self.assertEqual(len(calls), 1)
        sl.assert_not_called()

    def test_short_rate_limit_waits_for_hinted_delay(self):
        class Rate(Exception):
            code = 429

        llm, calls = self.make([Rate("limit per minute 'retryDelay': '12s'"), '{"ok": 1}'])
        with mock.patch("time.sleep") as sl:
            self.assertEqual(llm.complete_json("s", "sys", "p"), {"ok": 1})
        sl.assert_any_call(13.0)

    def test_fallback_model_used_when_first_is_gone_or_out_of_quota(self):
        class Gone(Exception):
            code = 404

        class Quota(Exception):
            code = 429

        for first_error in (Gone("no model"), Quota("PerDay limit")):
            mods, calls = fake_sdk([first_error, '{"a": 1}'])
            with mock.patch.dict(sys.modules, mods), mock.patch("time.sleep"):
                from validator.llm import GeminiLLM

                llm = GeminiLLM("key", "m1, m2", min_interval=0, retries=3)
                self.assertEqual(llm.complete_json("s", "sys", "p"), {"a": 1})
            self.assertEqual([c[0] for c in calls], ["m1", "m2"])
            self.assertEqual(llm.used, ["m2"])

    def test_gives_up_with_llm_error(self):
        from validator.llm import LLMError

        llm, _ = self.make([RuntimeError("x")] * 3)
        with mock.patch("time.sleep"), self.assertRaises(LLMError):
            llm.complete_json("s", "sys", "p")


if __name__ == "__main__":
    unittest.main()
