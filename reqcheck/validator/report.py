"""Сборка отчёта в Markdown по структуре из ТЗ организаторов."""
from collections import Counter

from .criteria import SEVERITIES, SEVERITY_RU, STANDARDS, name_ru, standard_ref
from .models import Finding, Result

KIND_RU = {"functional": "функц.", "nonfunctional": "нефункц.", "data": "данные", "interface": "интеграция/API",
           "constraint": "ограничение", "acceptance": "приёмка"}


def _cell(s: str, n: int = 140) -> str:
    s = " ".join(str(s).split()).replace("|", "/")
    return s if len(s) <= n else s[:n - 1] + "…"


def _where(f: Finding) -> str:
    parts = []
    for l in f.locs:
        p = f"стр. {l.page}, " if l.page else ""
        parts.append(f"{p}строка {l.line}, раздел «{l.section}»" if l.section else f"{p}строка {l.line}")
    return "; ".join(dict.fromkeys(parts))


def _finding(f: Finding) -> str:
    std = standard_ref(f.criterion)
    head = f"- **{f.fid} · {SEVERITY_RU[f.severity]} · {name_ru(f.criterion)}**" + (f" _({std})_" if std else "")
    out = [head, f"  - Где: {_where(f)}"]
    out += [f"  - Цитата: «{' '.join(q.split())}»" for q in f.quotes]
    out.append(f"  - Проблема: {f.problem}")
    if f.fix:
        out.append(f"  - Исправление: {f.fix}")
    return "\n".join(out)


def render(r: Result) -> str:
    items = [i for i in r.items if i.kind != "acceptance"]
    f_item = [f for f in r.findings if f.scope == "item"]
    f_set = [f for f in r.findings if f.scope == "set"]
    f_str = [f for f in r.findings if f.scope == "structure"]
    s, st = r.summary, r.stats
    L = ["# Отчёт о проверке качества требований", ""]

    L += ["## 1. Паспорт прогона", "", "| Параметр | Значение |", "| --- | --- |",
          f"| Документ | {r.doc_name} («{_cell(r.doc_title)}») |", f"| Дата и время | {r.started} |",
          f"| Модель | {r.model} |", f"| Версия агента | {r.version} |",
          f"| Вызовов LLM | {st.get('llm_calls', 0)} |", ""]
    L += ["_Номера строк указаны по тексту, извлечённому из документа._", ""]

    L += ["## 2. Нарезка требований", ""]
    if r.items:
        L += ["| ID в отчёте | ID в документе | Тип | Краткая формулировка | Цитата |", "| --- | --- | --- | --- | --- |"]
        for i in r.items:
            L.append(f"| {i.rid} | {i.doc_id or '— (присвоен ' + i.rid + ')'} | {KIND_RU.get(i.kind, i.kind)} | "
                     f"{_cell(i.summary, 80)} | {_cell(i.quote)} |")
    else:
        L.append("_Элементы не выделены (прогон без LLM или этап нарезки не выполнен)._")
    L.append("")

    L += ["## 3. Проверка каждого требования", ""]
    if not items:
        L += ["_Нет данных._", ""]
    for i in items:
        mine = [f for f in f_item if i.rid in f.targets]
        title = f"{i.rid}" + (f" ({i.doc_id})" if i.doc_id else "")
        L += [f"### {title}", f"> {_cell(i.quote, 300)}", ""]
        if i.rid in st.get("unchecked", []):
            L.append("Не проверено: модель не вернула результат для этого требования.")
        elif not mine:
            L.append("Нарушений не выявлено.")
        else:
            L += [_finding(f) for f in mine]
        L.append("")

    L += ["## 4. Проверка набора требований", ""]
    if f_set:
        L += [_finding(f) for f in f_set if f.source != "derived"]
        L.append("")
    covered_items = [i for i in r.items if i.rid in r.coverage]
    if covered_items:
        L += ["### Матрица покрытия критериями приёмки", "", "| Требование | Критерии приёмки |", "| --- | --- |"]
        for i in covered_items:
            cov = ", ".join(r.coverage[i.rid]) or "**не покрыто**"
            L.append(f"| {i.rid}{f' ({i.doc_id})' if i.doc_id else ''} | {cov} |")
        L.append("")
        L += [_finding(f) for f in f_set if f.source == "derived"] or []
        L.append("")
    if not f_set:
        L += ["Замечаний по набору не выявлено.", ""]

    L += ["## 5. Структура и оформление документа", ""]
    L += [_finding(f) for f in f_str] or ["Замечаний нет."]
    L.append("")

    cnt = Counter(f.severity for f in r.findings)
    L += ["## 6. Сводка", "", "| Показатель | Значение |", "| --- | --- |",
          f"| Выделено требований (без критериев приёмки) | {len(items)} |",
          f"| Выделено критериев приёмки | {len(r.items) - len(items)} |",
          f"| Всего замечаний | {len(r.findings)} |"]
    L += [f"| — {SEVERITY_RU[v].lower()} | {cnt[v]} |" for v in SEVERITIES]
    L += [f"| Требований без замечаний | {sum(1 for i in items if not any(i.rid in f.targets for f in f_item) and i.rid not in st.get('unchecked', []))} |",
          f"| Отсеяно как недостоверные (самопроверка) | {st.get('dropped_by_verify', 0)} |",
          f"| Отброшено из-за цитат, которых нет в документе | {st.get('dropped_ungrounded', 0) + st.get('dropped_items', 0)} |", ""]
    if st.get("failed_stages"):
        L += [f"> ⚠ Не выполнены этапы: {', '.join(st['failed_stages'])}. Отчёт неполон.", ""]
        if st.get("quota_exhausted"):
            L += ["> Исчерпана квота API. Повторите прогон позже: выполненные этапы берутся из кеша и квоту не тратят.", ""]
    by_crit = Counter(f.criterion for f in r.findings)
    if by_crit:
        L += ["**По критериям качества**", "", "| Критерий | Замечаний |", "| --- | --- |"]
        L += [f"| {name_ru(k)} | {n} |" for k, n in by_crit.most_common()]
        L.append("")
    crit = [f for f in r.findings if f.severity == "critical"]
    L.append("**Критичные дефекты**")
    L.append("")
    L += [f"- {f.fid} · {name_ru(f.criterion)} · {_where(f)}: {_cell(f.problem, 200)}" for f in crit] or ["Критичных дефектов нет."]
    L.append("")

    L += ["## 7. Итог", "",
          {True: "**Можно ли начинать разработку: да, критичных дефектов нет.**",
           False: "**Можно ли начинать разработку: нет, пока не устранены критичные дефекты.**",
           None: "**Можно ли начинать разработку: не определено (прогон без LLM).**"}[s.get("can_start")],
          "", s.get("verdict", ""), "", "**Что исправить в первую очередь**", ""]
    L += [f"{n}. {p}" for n, p in enumerate(s.get("priorities", []), 1)] or ["Приоритетных действий нет."]
    L.append("")
    return "\n".join(L)
