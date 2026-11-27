"""Устойчивость к кривым ответам модели: неверные типы полей не должны ронять прогон."""
import copy
import random
import unittest
from pathlib import Path

from tests.fakes import FakeLLM
from validator.document import load_document
from validator.pipeline import Pipeline
from validator.report import render

FIX = Path(__file__).parent / "fixtures" / "requirements.md"
DOC = load_document(str(FIX))
BAD = [None, 123, 1.5, True, [], {}, ["x"], [["y"]], {"a": 1}, "", "строка"]

Q = "Месяц определяется по дате совершения покупки в Алматы."

# один «мусорный» ответ, задевающий все места разбора ответа модели
GARBAGE = {
    "results": [{"id": ["R-001"], "violations": [{"criterion": ["x"], "severity": 5, "quote": ["q"], "problem": ["p"], "fix": {}},
                                                 {"criterion": None, "severity": [], "quote": 7, "problem": "есть", "fix": 3}]},
                {"id": "R-002", "violations": [{"criterion": ["x"], "severity": {}, "quote": Q, "problem": "p", "fix": []},
                                               {"criterion": {"a": 1}, "severity": [], "quote": Q, "problem": ["p"], "fix": "ok"},
                                               {"criterion": 5, "severity": 7, "quote": Q, "problem": "ещё", "fix": {"a": 1}}]},
                "строка", None, {"id": "R-003", "violations": "нет"}],
    "findings": [{"quotes": "строка", "ids": [["R-001"], 5], "problem": 5, "severity": {}, "criterion": []},
                 {"quotes": [Q], "criterion": ["x"], "severity": {}, "problem": "ok", "ids": [["R-001"], 5, "R-002"], "fix": []},
                 {"quotes": [Q, Q], "criterion": {"a": 1}, "severity": [], "problem": {"a": 1}, "fix": "f"},
                 {"quotes": [1, None, ["a"]], "problem": "x"}, 7, None],
    "coverage": [{"id": ["a"], "covered_by": "x"}, {"id": "R-001", "covered_by": [["R-006"], 5, None]}, "строка"],
    "verdicts": [{"id": ["T1"], "valid": False}, {"id": 3, "valid": False}, "x"],
    "verdict": {"a": 1}, "priorities": "abc",
    "items": "x",
}


class AfterSegmentation(FakeLLM):
    """Нарезка корректна, все остальные этапы возвращают заданный мусор."""

    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    def complete_json(self, stage, system, prompt):
        if stage.startswith("нарезка"):
            return super().complete_json(stage, system, prompt)
        self.stages.append(stage)
        return self.payload


class MutatingLLM(FakeLLM):
    def __init__(self, seed):
        super().__init__()
        self.rng = random.Random(seed)

    def _mutate(self, obj, p=0.15):
        if self.rng.random() < p:
            return self.rng.choice(BAD)
        if isinstance(obj, dict):
            return {k: self._mutate(v, p) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._mutate(v, p) for v in obj]
        return obj

    def complete_json(self, stage, system, prompt):
        try:
            good = super().complete_json(stage, system, prompt)
        except AttributeError:  # заглушка не нашла требование в испорченной нарезке
            good = {}
        if self.rng.random() < 0.1:
            return self.rng.choice([None, [], "текст", 5, [1, "a"], {"items": "x"}, {"findings": None}, {"results": {}}])
        return self._mutate(copy.deepcopy(good))


def run(llm):
    res = Pipeline(DOC, llm, "m", log=lambda m: None).run()
    return res, render(res)


class Robustness(unittest.TestCase):
    def test_garbage_in_every_stage_after_segmentation(self):
        for payload in (GARBAGE, None, 5, "текст", [], [1, "a"], {}):
            with self.subTest(payload=str(payload)[:40]):
                res, text = run(AfterSegmentation(payload))
                self.assertIn("## 7. Итог", text)
                self.assertTrue(res.items)

    def test_malformed_segmentation_items_are_skipped_not_fatal(self):
        class BadSegment(FakeLLM):
            def complete_json(self, stage, system, prompt):
                if stage.startswith("нарезка"):
                    return {"items": [
                        {"quote": ["список"], "kind": ["x"], "summary": 5, "doc_id": [1]},
                        {"quote": 7}, "строка", None,
                        {"quote": "Месяц определяется по дате совершения покупки в Алматы.", "kind": {"a": 1},
                         "summary": ["s"], "doc_id": 12},
                    ]}
                return {}

        res, text = run(BadSegment())
        self.assertEqual(len(res.items), 1)  # остался только элемент с настоящей цитатой
        self.assertEqual(res.items[0].kind, "functional")  # неверный kind заменён значением по умолчанию
        self.assertIsNone(res.items[0].doc_id)

    def test_garbage_never_produces_findings_without_valid_quote(self):
        res, _ = run(AfterSegmentation(GARBAGE))
        for f in res.findings:
            self.assertTrue(all(isinstance(q, str) for q in f.quotes))
            self.assertTrue(f.locs)

    def test_seeded_random_corruption_of_model_answers(self):
        crashed = []
        for seed in range(300):
            try:
                _, text = run(MutatingLLM(seed))
                self.assertIn("## 7. Итог", text)
            except Exception as e:  # noqa: BLE001 — собираем все падения
                crashed.append((seed, type(e).__name__, str(e)[:80]))
        self.assertEqual(crashed, [])


if __name__ == "__main__":
    unittest.main()
