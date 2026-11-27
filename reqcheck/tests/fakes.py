"""Подставная модель для тестов: отвечает заготовленным JSON по названию этапа."""
import re

Q = {
    "f1": "Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.",
    "f2": "Месяц определяется по дате совершения покупки в Алматы.",
    "f3": "На карту приходится максимум один такой push за календарный месяц.",
    "f4": "Если она ниже нового порога, следующее достижение вызывает push независимо от истории предыдущей настройки.",
    "ac2": "Покупка 31 января в 23:58 на 4 000 ₸ | Провести 1 февраля в 00:03 по Алматы | Февральский счётчик вырос на 4 000 ₸",
    "nfr": "Сервис передаёт push на отправку в течение минуты после получения события.",
}


class FakeLLM:
    calls = 0

    def __init__(self):
        self.stages = []

    def complete_json(self, stage, system, prompt):
        self.stages.append(stage)
        self.calls += 1
        if stage.startswith("нарезка"):
            return {"items": [
                {"doc_id": "Ф-1", "kind": "functional", "quote": Q["f1"], "summary": "порог от 1000 до 1000000"},
                {"doc_id": "Ф-2", "kind": "functional", "quote": Q["f2"], "summary": "месяц по дате покупки"},
                {"doc_id": "Ф-3", "kind": "functional", "quote": Q["f3"], "summary": "один push в месяц"},
                {"doc_id": "Ф-4", "kind": "functional", "quote": Q["f4"], "summary": "смена порога"},
                {"doc_id": None, "kind": "nonfunctional", "quote": Q["nfr"], "summary": "push за минуту"},
                {"doc_id": None, "kind": "acceptance", "quote": Q["ac2"], "summary": "кейс 31 января"},
                {"doc_id": "Ф-9", "kind": "functional", "quote": "Выдуманное требование, которого нет в документе.", "summary": "выдумка"},
            ]}
        rid = lambda did: re.search(rf"(R-\d+) \[{did}\]", prompt).group(1)
        if stage.startswith("проверка требований"):
            return {"results": [
                {"id": rid("Ф-3"), "violations": [
                    {"criterion": "verifiable", "severity": "major", "quote": Q["f3"], "problem": "Настоящее замечание.", "fix": "Уточнить."},
                    {"criterion": "unambiguous", "severity": "minor", "quote": "цитата которой нет нигде", "problem": "ЛОЖНОЕ: придирка.", "fix": ""}]},
                {"id": rid("Ф-1"), "violations": []},
            ]}
        if stage == "противоречия":
            return {"findings": [
                {"severity": "critical", "ids": [rid("Ф-3"), rid("Ф-4")], "quotes": [Q["f3"], Q["f4"]],
                 "problem": "Ф-3 допускает один push в месяц, Ф-4 требует push независимо от истории.", "fix": "Определить приоритет."},
                {"severity": "critical", "ids": [], "quotes": [Q["f1"], "выдуманная вторая цитата"],
                 "problem": "Противоречие с одной несуществующей цитатой.", "fix": ""},
            ]}
        if stage == "пропуски":
            return {"findings": [
                {"severity": "major", "ids": [], "quotes": ["полностью выдуманная цитата"], "problem": "Пропуск без опоры.", "fix": ""},
                {"severity": "major", "ids": [], "quotes": [Q["nfr"]], "problem": "НФТ без метрики измерения.", "fix": "Указать перцентиль."},
            ]}
        if stage.startswith("сверка"):
            return {"findings": []}
        if stage.startswith("покрытие"):
            tests = re.findall(r"^(R-\d+): ", prompt.split("КРИТЕРИИ:")[1], re.M)
            return {"coverage": [{"id": rid("Ф-1"), "covered_by": []}, {"id": rid("Ф-2"), "covered_by": tests},
                                 {"id": rid("Ф-3"), "covered_by": []}, {"id": rid("Ф-4"), "covered_by": []}]}
        if stage.startswith("самопроверка"):
            ids = re.findall(r'"id": "(T\d+)",\s+"criterion": "[a-z_]+",\s+"quotes": \[[^\]]*\],\s+"problem": "(ЛОЖНОЕ)?', prompt)
            return {"verdicts": [{"id": i, "valid": not bad, "reason": "тест"} for i, bad in ids]}
        if stage == "итог":
            return {"verdict": "Есть критичное противоречие Ф-3/Ф-4.", "priorities": ["Разрешить противоречие (F-001)."]}
        raise AssertionError(f"неожиданный этап {stage}")
