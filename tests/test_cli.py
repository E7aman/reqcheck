import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from validator.cli import main

FIX = str(Path(__file__).parent / "fixtures" / "requirements.md")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.old_cwd, self.old_env = os.getcwd(), dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)  # чтобы не подхватить настоящий .env
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.clear(), os.environ.update(self.old_env)
        self.tmp.cleanup()

    def run_cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, err.getvalue()

    def test_lint_only_writes_report_and_json(self):
        code, _ = self.run_cli(FIX, "out/report.md", "--lint-only", "--json", "out/r.json")
        self.assertEqual(code, 0)
        self.assertIn("## 7. Итог", Path("out/report.md").read_text(encoding="utf-8"))
        self.assertTrue(json.loads(Path("out/r.json").read_text(encoding="utf-8"))["findings"])

    def _patched_cli(self, fake):
        from unittest import mock

        os.environ["GEMINI_API_KEY"] = "dummy-key-for-test"
        return mock.patch("validator.cli.GeminiLLM", lambda key, model, interval: fake)

    def test_full_run_with_fake_llm_writes_complete_report_without_warning(self):
        from tests.fakes import FakeLLM

        with self._patched_cli(FakeLLM()):
            code, err = self.run_cli(FIX, "o/r.md", "--no-cache", "--json", "o/r.json")
        self.assertEqual(code, 0)
        self.assertNotIn("ВНИМАНИЕ", err)
        data = json.loads(Path("o/r.json").read_text(encoding="utf-8"))
        self.assertIs(data["summary"]["can_start"], False)  # в подставном ответе есть критичное противоречие
        self.assertIn("Проверка набора требований", Path("o/r.md").read_text(encoding="utf-8"))

    def test_partial_run_exits_zero_but_warns_loudly(self):
        from tests.fakes import FakeLLM
        from validator.llm import LLMQuotaError

        class QuotaOnSet(FakeLLM):
            def complete_json(self, stage, system, prompt):
                if stage.startswith("противоречия"):
                    raise LLMQuotaError("квота")
                return super().complete_json(stage, system, prompt)

        with self._patched_cli(QuotaOnSet()):
            code, err = self.run_cli(FIX, "o/r.md", "--no-cache")
        self.assertEqual(code, 0)
        self.assertIn("ВНИМАНИЕ: отчёт неполный", err)
        self.assertTrue(Path("o/r.md").exists())

    def test_fatal_api_error_exits_3_without_report(self):
        from validator.llm import LLMFatalError

        class Dead:
            calls = 0

            def complete_json(self, *a):
                raise LLMFatalError("Gemini вернул ошибку 401")

        with self._patched_cli(Dead()):
            code, err = self.run_cli(FIX, "o/r.md", "--no-cache")
        self.assertEqual(code, 3)
        self.assertIn("401", err)
        self.assertFalse(Path("o/r.md").exists())

    def test_missing_key_gives_clear_error(self):
        code, err = self.run_cli(FIX, "r.md")
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY", err)
        self.assertFalse(Path("r.md").exists())

    def test_missing_file_and_bad_format(self):
        self.assertEqual(self.run_cli("nope.md", "r.md", "--lint-only")[0], 2)
        Path("a.xyz").write_text("x")
        self.assertEqual(self.run_cli("a.xyz", "r.md", "--lint-only")[0], 2)


if __name__ == "__main__":
    unittest.main()
