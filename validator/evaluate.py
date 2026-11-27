"""Сверка находок агента с эталонным списком дефектов.

python -m validator.evaluate result.json tests/gold/requirements_gold.json
Дефект считается найденным, если в одной находке (цитаты + проблема) встречаются все слова из любой группы `any_of`.
"""
import json
import sys


def evaluate(result: dict, gold: dict) -> dict:
    texts = [" ".join(f.get("quotes", []) + [f.get("problem", ""), f.get("fix", "")]).lower()
             for f in result["findings"]]
    found, missed = [], []
    for d in gold["defects"]:
        hit = any(all(w.lower() in t for w in group) for group in d["any_of"] for t in texts)
        (found if hit else missed).append(d["id"])
    return {"total": len(gold["defects"]), "found": found, "missed": missed,
            "recall": round(len(found) / len(gold["defects"]), 2), "findings_total": len(texts)}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    res = evaluate(json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8")))
    print(f"Найдено эталонных дефектов: {len(res['found'])} из {res['total']} (полнота {res['recall']:.0%}); "
          f"всего замечаний агента: {res['findings_total']}")
    if res["missed"]:
        print("Пропущено:", ", ".join(res["missed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
