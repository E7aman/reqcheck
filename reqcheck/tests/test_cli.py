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
