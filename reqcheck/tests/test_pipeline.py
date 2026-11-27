import json
import tempfile
import unittest
from pathlib import Path

from validator.document import load_document
from validator.llm import CachedLLM, extract_json
from validator.pipeline import Pipeline
from validator.report import render
from tests.fakes import FakeLLM

FIX = Path(__file__).parent / "fixtures" / "requirements.md"


def run(verify=True):
    llm = FakeLLM()
    res = Pipeline(load_document(str(FIX)), llm, "fake-model", verify=verify, log=lambda m: None).run()
    return res, llm


class PipelineWithFakeLLM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, cls.llm = run()
        cls.text = render(cls.res)

    def test_segmentation_drops_invented_item_and_assigns_ids(self):
        self.assertEqual(len(self.res.items), 6)
        self.assertEqual(self.res.stats["dropped_items"], 1)
        self.assertEqual([i.rid for i in self.res.items], [f"R-00{n}" for n in range(1, 7)])
        self.assertEqual(sorted(i.doc_id for i in self.res.items if i.doc_id), ["Ф-1", "Ф-2", "Ф-3", "Ф-4"])
        self.assertTrue(all(i.loc and i.loc.line > 0 for i in self.res.items))

    def test_ungrounded_set_findings_are_dropped(self):
        # пропуск с выдуманной цитатой и противоречие с одной найденной цитатой из двух
        self.assertEqual(self.res.stats["dropped_ungrounded"], 2)
        self.assertFalse(any("Пропуск без опоры" in f.problem for f in self.res.findings))
        self.assertFalse(any("одной несуществующей" in f.problem for f in self.res.findings))

    def test_contradiction_has_two_real_locations(self):
        c = next(f for f in self.res.findings if f.criterion == "consistent")
        self.assertEqual(c.severity, "critical")
        self.assertEqual(len(c.locs), 2)
        self.assertEqual(len(c.targets), 2)

    def test_verify_removes_false_item_finding(self):
        self.assertEqual(self.res.stats["dropped_by_verify"], 1)
        self.assertFalse(any("ЛОЖНОЕ" in f.problem for f in self.res.findings))
        self.assertTrue(any("Настоящее замечание" in f.problem for f in self.res.findings))

    def test_ungrounded_item_quote_falls_back_to_requirement_text(self):
        res, _ = run(verify=False)
        f = next(f for f in res.findings if "ЛОЖНОЕ" in f.problem)
        self.assertEqual(f.quotes, [next(i.quote for i in res.items if i.doc_id == "Ф-3")])

    def test_coverage_matrix_and_derived_findings(self):
        by_doc = {i.doc_id: i.rid for i in self.res.items if i.doc_id}
        self.assertEqual(len(self.res.coverage[by_doc["Ф-2"]]), 1)
        self.assertEqual(self.res.coverage[by_doc["Ф-1"]], [])
        uncovered = [f for f in self.res.findings if f.source == "derived"]
        self.assertEqual(len(uncovered), 3)  # Ф-1, Ф-3, Ф-4
        self.assertTrue(all(f.severity == "major" for f in uncovered))

    def test_lint_and_llm_findings_merged_and_numbered(self):
        ids = [f.fid for f in self.res.findings]
        self.assertEqual(ids, [f"F-{n:03d}" for n in range(1, len(ids) + 1)])
        self.assertTrue(any(f.source == "lint" for f in self.res.findings))
        sev = [f.severity for f in self.res.findings]
        self.assertEqual(sev, sorted(sev, key=["critical", "major", "minor"].index))

    def test_summary_rule_is_decided_by_code(self):
        self.assertFalse(self.res.summary["can_start"])  # есть критичное противоречие
        self.assertIn("Ф-3/Ф-4", self.res.summary["verdict"])

    def test_report_has_all_required_sections(self):
        for h in ("## 1. Паспорт прогона", "## 2. Нарезка требований", "## 3. Проверка каждого требования",
                  "## 4. Проверка набора требований", "## 5. Структура и оформление документа",
                  "## 6. Сводка", "## 7. Итог"):
            self.assertIn(h, self.text)
        self.assertIn("fake-model", self.text)
        self.assertIn("Матрица покрытия", self.text)
        self.assertIn("| R-003 | Ф-3 |", self.text)
        self.assertIn("нет, пока не устранены критичные дефекты", self.text)

    def test_report_never_contains_ungrounded_quotes(self):
        doc = load_document(str(FIX))
        for f in self.res.findings:
            for q in f.quotes:
                self.assertIsNotNone(doc.locate(q))


class Resilience(unittest.TestCase):
    def test_failed_stage_yields_partial_report_not_crash(self):
        from validator.llm import LLMError

        class Flaky(FakeLLM):
            def complete_json(self, stage, system, prompt):
                if stage == "пропуски":
                    raise LLMError("лимит")
                return super().complete_json(stage, system, prompt)

        res = Pipeline(load_document(str(FIX)), Flaky(), "m", log=lambda m: None).run()
        self.assertEqual(res.stats["failed_stages"], ["пропуски"])
        self.assertIn("Не выполнены этапы: пропуски", render(res))

    def test_quota_error_stops_llm_calls_and_keeps_partial_report(self):
        from validator.llm import LLMQuotaError

        class QuotaAfterSegment(FakeLLM):
            def complete_json(self, stage, system, prompt):
                if stage.startswith("противоречия"):
                    raise LLMQuotaError("квота")
                return super().complete_json(stage, system, prompt)

        llm = QuotaAfterSegment()
        res = Pipeline(load_document(str(FIX)), llm, "m", log=lambda m: None).run()
        self.assertTrue(res.stats["quota_exhausted"])
        self.assertEqual(res.stats["failed_stages"][0], "противоречия")
        self.assertTrue(all("(пропущен)" in x for x in res.stats["failed_stages"][1:]))
        # после ошибки квоты модель больше не вызывается
        for later in ("пропуски", "покрытие", "самопроверка", "итог"):
            self.assertFalse(any(st.startswith(later) for st in llm.stages), later)
        text = render(res)
        self.assertIn("Исчерпана квота API", text)
        self.assertTrue(res.items and res.findings)  # нарезка и структурные находки сохранены

    def test_failed_segmentation_skips_paid_stages(self):
        from validator.llm import LLMError

        class NoSegment(FakeLLM):
            def complete_json(self, stage, system, prompt):
                if stage.startswith("нарезка"):
                    raise LLMError("503")
                raise AssertionError(f"не должно вызываться: {stage}")

        res = Pipeline(load_document(str(FIX)), NoSegment(), "m", log=lambda m: None).run()
        self.assertIn("смысловой анализ (нет нарезки)", res.stats["failed_stages"])
        self.assertTrue(res.findings)  # структурные находки на месте

    def test_fatal_error_aborts_run(self):
        from validator.llm import LLMFatalError

        class Dead(FakeLLM):
            def complete_json(self, stage, system, prompt):
                raise LLMFatalError("404")

        with self.assertRaises(LLMFatalError):
            Pipeline(load_document(str(FIX)), Dead(), "m", log=lambda m: None).run()

    def test_lint_only_mode_makes_no_verdict(self):
        res = Pipeline(load_document(str(FIX)), None, log=lambda m: None).run()
        self.assertIsNone(res.summary["can_start"])
        self.assertIn("не определено", render(res))
        self.assertTrue(res.findings)


class LLMLayer(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertEqual(extract_json('Вот ответ: {"a": 1} Готово.'), {"a": 1})
        with self.assertRaises(ValueError):
            extract_json("никакого json")

    def test_cache_returns_same_answer_without_second_call(self):
        class Counter:
            n = 0

            def complete_json(self, stage, system, prompt):
                Counter.n += 1
                return {"n": Counter.n}

        with tempfile.TemporaryDirectory() as d:
            c = CachedLLM(Counter(), "m", d)
            a, b = c.complete_json("s", "sys", "p"), c.complete_json("s", "sys", "p")
            self.assertEqual(a, b)
            self.assertEqual((Counter.n, c.hits), (1, 1))
            self.assertNotEqual(c.complete_json("s", "sys", "other"), a)


if __name__ == "__main__":
    unittest.main()
