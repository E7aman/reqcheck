"""Детерминированные проверки структуры и оформления. Не используют LLM: быстро, воспроизводимо, без выдумок."""
import re
from collections import defaultdict

from .document import HEADING_RE, Document, norm
from .models import Finding

# расплывчатые формулировки: (regex, как назвать)
VAGUE = [
    (r"и\s+далее", "«и далее»"), (r"и\s+т\.\s?д\.", "«и т. д.»"), (r"и\s+т\.\s?п\.", "«и т. п.»"),
    (r"и\s+(?:другие|прочие)", "«и другие»"), (r"и\s+пр\.", "«и пр.»"),
    (r"при\s+необходимости", "«при необходимости»"), (r"по\s+возможности", "«по возможности»"),
    (r"как\s+правило", "«как правило»"), (r"\bбыстр\w*", "«быстро»"), (r"\bоперативн\w*", "«оперативно»"),
    (r"\bудобн\w*", "«удобно»"), (r"\bэффективн\w*", "«эффективно»"), (r"\bинтуитивн\w*", "«интуитивно»"),
    (r"\bдостаточн\w*", "«достаточно»"), (r"\bприемлем\w*", "«приемлемо»"), (r"\bадекватн\w*", "«адекватно»"),
    (r"\bсоответствующ\w*", "«соответствующий»"), (r"\bнекоторы\w*", "«некоторые»"),
    (r"\bmaximally\b|\bмаксимально\b", "«максимально»"),
]
VAGUE_MAX_PER_TERM = 3

HTTP_NAMES = {"created": 201, "bad request": 400, "unauthorized": 401, "forbidden": 403,
              "not found": 404, "internal server error": 500}
WRITE_WORDS = r"save|update|delete|remove|create|set|add|edit|change|сохран|удал|созда|изменени|обнов|запис"
EMPTY_CELLS = {"", "—", "–", "-", "n/a", "tbd", "нет данных"}


def _code_free(doc: Document):
    """Номера и тексты строк вне блоков ```."""
    inside = False
    for i, ln in enumerate(doc.lines, 1):
        if ln.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            yield i, ln


def _cells(line: str):
    line = line.strip()
    if not line.startswith("|"):
        return None
    return [c.strip().strip("*").strip() for c in line.strip("|").split("|")]


def _is_sep(cells) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells)


def _tables(doc: Document):
    """Таблицы как списки (номер строки, ячейки); разделитель --- пропущен."""
    cur = []
    for i, ln in _code_free(doc):
        c = _cells(ln)
        if c is None:
            if cur:
                yield cur
            cur = []
        elif not _is_sep(c):
            cur.append((i, c, ln))
    if cur:
        yield cur


def _f(criterion, severity, quotes, problem, fix="") -> Finding:
    return Finding("structure", criterion, severity, quotes, problem, fix, source="lint")


def check_placeholders(doc: Document):
    groups = defaultdict(list)
    for i, ln in _code_free(doc):
        if re.search(r"Да\s*/\s*Нет", ln):
            groups["checklist"].append(ln)
        if re.search(r"заполня[юе]тся", ln, re.I):
            groups["deferred"].append(ln)
        if re.search(r"не\s+заполнен", ln, re.I):
            groups["notfilled"].append(ln)
        if re.search(r"\bTBD\b|\bTODO\b|\bFIXME\b|\?\?\?|\bXXX\b", ln):
            groups["marker"].append(ln)
    out = []
    if groups["checklist"]:
        n = len(groups["checklist"])
        out.append(_f("conforming", "major", groups["checklist"][:2],
                      f"В документе остались неотмеченные варианты «Да / Нет» ({n} строк): чек-лист ревью не заполнен, "
                      "то есть полнота и качество требований формально не подтверждены.",
                      "Пройти чек-лист и проставить отметки с примечаниями либо исключить пункты, которые не применимы."))
    if groups["deferred"]:
        out.append(_f("complete", "major", groups["deferred"][:3],
                      "Раздел отложен («заполняются позже»): требования к тестированию не описаны.",
                      "Заполнить раздел до передачи в разработку или явно указать ответственного и срок."))
    if groups["notfilled"]:
        out.append(_f("conforming", "minor", groups["notfilled"][:3],
                      "Документ сам фиксирует, что обязательные поля шаблона не заполнены.",
                      "Заполнить указанные поля."))
    if groups["marker"]:
        out.append(_f("complete", "major", groups["marker"][:3],
                      "В тексте остались маркеры незавершённости (TBD/TODO/???).", "Закрыть или убрать маркеры."))
    return out


def check_empty_table_parts(doc: Document):
    out, empty_rows, kv_empty = [], [], []
    for t in _tables(doc):
        header = t[0]
        for i, cells, raw in t[1:]:
            if all(not c for c in cells):
                empty_rows.append((header[2], i))
        h = [norm(c) for c in header[1]]
        if len(h) == 2 and h[0] in ("поле", "field", "параметр", "parameter") and h[1] in ("значение", "value"):
            for i, cells, raw in t[1:]:
                val = cells[1] if len(cells) > 1 else ""
                inline = re.search(r"\b(Dev|Test|Stage|Prod)\w*\s*:\s*[—–-](?:\s|\.|$)", val)
                if val.strip().lower() in EMPTY_CELLS or inline:
                    kv_empty.append((cells[0], raw))
    if empty_rows:
        out.append(_f("conforming", "major", [r[0] for r in empty_rows[:2]],
                      "Таблица содержит пустые строки (не заполнена): например, блок согласующих без ФИО и подписей.",
                      "Заполнить таблицу или удалить пустые строки."))
    if kv_empty:
        names = ", ".join(sorted({k for k, _ in kv_empty}))
        out.append(_f("complete", "minor", [r for _, r in kv_empty[:3]],
                      f"В таблицах «Поле/Значение» не заполнены значения: {names}.",
                      "Заполнить значения либо явно указать «не применимо» с причиной."))
    return out


def check_vague(doc: Document):
    out = []
    for pattern, label in VAGUE:
        hits = [ln for _, ln in _code_free(doc) if re.search(pattern, ln, re.I) and not re.search(r"Да\s*/\s*Нет", ln)]
        for ln in hits[:VAGUE_MAX_PER_TERM]:
            out.append(_f("unambiguous", "minor", [ln.strip()],
                          f"Расплывчатая формулировка {label}: нельзя однозначно определить границы и проверить.",
                          "Заменить конкретным перечнем или измеримым значением."))
    return out


def check_http(doc: Document):
    out, method, url, desc = [], None, None, ""
    for t in _tables(doc):
        for _, cells, raw in t:
            if len(cells) < 2:
                continue
            k = norm(cells[0])
            if k == "rest type":
                method = (cells[1].upper(), raw)
            elif k == "request url":
                url = (cells[1], raw)
            elif k == "description":
                desc = cells[1]
    if method and url and method[0] == "GET" and re.search(WRITE_WORDS, url[0] + " " + desc, re.I):
        out.append(_f("correct", "major", [method[1], url[1]],
                      "Метод изменяет состояние (сохранение настройки), но описан как GET. GET должен быть безопасным "
                      "и идемпотентным; запись через GET кешируется, попадает в логи и уязвима к CSRF. Глагол в URL "
                      "также противоречит REST-стилю.",
                      "Использовать PUT или POST с телом запроса, а ресурс назвать существительным (например, /cards/{id}/alert-limit)."))
    # Content-Type при неиспользуемом теле
    for i, ln in enumerate(doc.lines):
        if re.search(r"request body", ln, re.I):
            win = doc.lines[i:i + 5]
            ct = next((w for w in win if re.search(r"application/json", w, re.I)), None)
            nb = next((w for w in win if re.search(r"не используется|not used", w, re.I)), None)
            if ct and nb:
                out.append(_f("correct", "minor", [ct.strip(), nb.strip()],
                              "Указан Content-Type: application/json, хотя тело запроса не используется.",
                              "Убрать Content-Type или описать тело запроса."))
            break
    # заголовки статусов: код против названия и против содержимого
    heads = [(i, m) for i, ln in enumerate(doc.lines)
             if (m := re.match(r"^#{2,6}\s*(\d{3})\.?\s*(.*)$", ln))]
    for n, (i, m) in enumerate(heads):
        code, rest = int(m.group(1)), m.group(2).lower()
        for name, expected in HTTP_NAMES.items():
            if name in rest and expected != code:
                out.append(_f("correct", "major", [doc.lines[i].strip()],
                              f"Код {code} в заголовке не соответствует названию «{name}» ({expected}).",
                              f"Привести код и название в соответствие: {expected} или другое название."))
        end = heads[n + 1][0] if n + 1 < len(heads) else len(doc.lines)
        body, inside = [], False
        for ln in doc.lines[i + 1:end]:
            if ln.strip().startswith("```"):
                inside = not inside
            elif not inside and not re.match(r"^\*\*\d{3}\.\*\*", ln.strip()):  # строки перечня статусов — не содержимое раздела
                body.append(ln)
        codes = {int(c) for c in re.findall(r"(?<![\d.])([1-5]\d\d)(?![\d%])", "\n".join(body))}
        if codes and code not in codes:
            other = sorted(codes)[0]
            line = next(b for b in body if str(other) in b)
            described = any(int(h.group(1)) == other for _, h in heads) or re.search(rf"\*\*{other}\.", doc.text)
            tail = "" if described else f" Код {other} при этом не описан отдельным пунктом перечня статусов."
            out.append(_f("correct", "major", [doc.lines[i].strip(), line.strip()],
                          f"Раздел помечен кодом {code}, а описывает ответ {other}.{tail}",
                          f"Привести заголовок в соответствие с содержимым и добавить код {other} в перечень статусов."))
    return out


def check_numbering(doc: Document):
    ids = defaultdict(list)
    for i, ln in _code_free(doc):
        m = re.match(r"^\s*[*\-]?\s*\*{0,2}([A-Za-zА-Яа-я]{1,5})-(\d+)\.?\*{0,2}", ln)
        if m:
            ids[m.group(1)].append((int(m.group(2)), ln))
    out = []
    for prefix, lst in ids.items():
        nums = [n for n, _ in lst]
        for n in sorted({x for x in nums if nums.count(x) > 1}):
            ln = next(l for x, l in lst if x == n)
            out.append(_f("traceable", "major", [ln.strip()], f"Идентификатор {prefix}-{n} встречается несколько раз.",
                          "Дать каждому требованию уникальный идентификатор."))
        gaps = [n for n in range(1, max(nums) + 1) if n not in nums]
        if gaps:
            out.append(_f("traceable", "minor", [lst[0][1].strip()],
                          f"Нумерация {prefix}- имеет пропуски: нет {', '.join(f'{prefix}-{g}' for g in gaps)}.",
                          "Восстановить пропущенные требования или перенумеровать."))
    return out


def check_version(doc: Document):
    t = doc.text
    has_date = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b|\b\d{4}-\d{2}-\d{2}\b", t)
    has_ver = re.search(r"верси[яи]\s*[:|]?\s*v?\d|\bv\d+\.\d+|version\s*[:|]?\s*\d", t, re.I)
    if has_date or has_ver:
        return []
    first = next((ln for ln in doc.lines if ln.strip()), "")
    return [_f("conforming", "minor", [first.strip()],
               "В документе не указаны версия и дата: нельзя понять, какая редакция требований согласована.",
               "Добавить версию, дату и историю изменений.")]


def check_empty_sections(doc: Document):
    out = []
    for i, ln in enumerate(doc.lines):
        if not HEADING_RE.match(ln):
            continue
        nxt = next((x for x in doc.lines[i + 1:] if x.strip() and x.strip() != "---"), None)
        if nxt is None or HEADING_RE.match(nxt):
            # заголовок без текста; если следом заголовок ниже уровнем, это раздел-контейнер
            if nxt and len(HEADING_RE.match(nxt).group(1)) > len(HEADING_RE.match(ln).group(1)):
                continue
            out.append(_f("complete", "major", [ln.strip()], "Раздел пуст: после заголовка нет содержимого.",
                          "Заполнить раздел или удалить заголовок."))
    return out


def run_lint(doc: Document) -> list[Finding]:
    out = []
    for check in (check_placeholders, check_empty_table_parts, check_empty_sections, check_http,
                  check_numbering, check_version, check_vague):
        out += check(doc)
    return out
