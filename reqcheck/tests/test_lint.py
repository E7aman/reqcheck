import json
import unittest
from pathlib import Path

from validator.document import Document, load_document
from validator.evaluate import evaluate
from validator.lint import run_lint

HERE = Path(__file__).parent
GOLD = json.load(open(HERE / "gold" / "requirements_gold.json", encoding="utf-8"))


def lint(text):
    return run_lint(Document(text))


class LintOnFixture(unittest.TestCase):
    def test_finds_every_lint_layer_gold_defect(self):
        doc = load_document(str(HERE / "fixtures" / "requirements.md"))
        findings = run_lint(doc)
        result = {"findings": [{"quotes": f.quotes, "problem": f.problem, "fix": f.fix} for f in findings]}
        gold = {"defects": [d for d in GOLD["defects"] if d["layer"] == "lint"]}
        ev = evaluate(result, gold)
        self.assertEqual(ev["missed"], [], ev)

    def test_every_lint_quote_exists_in_document(self):
        doc = load_document(str(HERE / "fixtures" / "requirements.md"))
        for f in run_lint(doc):
            for q in f.quotes:
                self.assertIsNotNone(doc.locate(q), q)

    def test_status_index_lines_do_not_trigger_false_positive(self):
        doc = load_document(str(HERE / "fixtures" / "requirements.md"))
        bad = [f for f in run_lint(doc) if "описывает ответ 401" in f.problem or "описывает ответ 400" in f.problem]
        self.assertEqual(bad, [])


class LintRules(unittest.TestCase):
    CLEAN = "# Док\n\nВерсия: 1.2 от 01.02.2026\n\n## Требования\n\n* **Ф-1.** Система округляет сумму до целых тенге.\n* **Ф-2.** Система хранит сумму в тиынах.\n"

    def test_clean_document_has_no_findings(self):
        self.assertEqual(lint(self.CLEAN), [])

    def test_duplicate_and_gap_ids(self):
        text = self.CLEAN + "* **Ф-2.** Ещё одно требование.\n* **Ф-5.** Пропуск.\n"
        msgs = " ".join(f.problem for f in lint(text))
        self.assertIn("Ф-2 встречается несколько раз", msgs)
        self.assertIn("Ф-3", msgs)

    def test_empty_section_flagged_but_container_not(self):
        flagged = lint(self.CLEAN + "\n## Пустой\n\n## Следующий\nтекст\n")
        self.assertTrue(any("Раздел пуст" in f.problem for f in flagged))
        container = lint(self.CLEAN + "\n## Родитель\n\n### Дочерний\nтекст\n")
        self.assertFalse(any("Раздел пуст" in f.problem for f in container))

    def test_get_with_write_verb_only_when_get(self):
        tpl = "# Док\nверсия: 1.0\n\n| Поле | Значение |\n| --- | --- |\n| **REST type** | {m} |\n| **Request URL** | /alerts/saveLimit |\n"
        self.assertTrue(any("GET" in f.problem for f in lint(tpl.format(m="GET"))))
        self.assertFalse(any("GET" in f.problem for f in lint(tpl.format(m="PUT"))))

    def test_vague_words_capped_per_term_and_skip_code(self):
        text = self.CLEAN + "\n" + "\n".join(f"* Система работает быстро, случай {i}." for i in range(8))
        text += "\n```\nбыстро и далее\n```\n"
        vague = [f for f in lint(text) if "быстро" in f.problem]
        self.assertEqual(len(vague), 3)


if __name__ == "__main__":
    unittest.main()
