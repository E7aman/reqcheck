"""Загрузка документа (md/txt/pdf/docx) в единый текст и поиск цитат в нём."""
import bisect
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
PAGE_RE = re.compile(r"^<!-- стр\. (\d+) -->$")


def norm(s: str) -> str:
    """Нормализация для сравнения цитат: без markdown-разметки, регистра, ё и вида кавычек/тире."""
    s = s.replace("ё", "е").replace("Ё", "Е")
    s = re.sub(r"[*`|#>_]", " ", s)
    s = re.sub(r"[«»“”„‟\"'’]", "", s)
    s = re.sub(r"[—–−‑]", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _grams(s: str, n: int = 4) -> set:
    return {s[i:i + n] for i in range(max(len(s) - n + 1, 1))} if s else set()


@dataclass
class Loc:
    line: int      # 1-based, по извлечённому тексту
    section: str
    page: int | None
    exact: bool
    text: str      # фрагмент документа, на который сослались


class Document:
    def __init__(self, text: str, name: str = "document"):
        self.name = name
        self.text = text
        self.lines = text.splitlines()
        self._norm_lines = [norm(x) for x in self.lines]
        # один длинный нормализованный текст и смещения начала каждой строки
        self._full, self._starts, pos = "", [], 0
        for n in self._norm_lines:
            self._starts.append(pos)
            self._full += n + " "
            pos += len(n) + 1
        self._sections, self._pages = self._index()
        self._grams = [_grams(n) for n in self._norm_lines]

    def _index(self):
        sections, pages, cur, page = [], [], "", None
        for ln in self.lines:
            m = HEADING_RE.match(ln)
            if m:
                cur = m.group(2).strip("* ")
            pm = PAGE_RE.match(ln.strip())
            if pm:
                page = int(pm.group(1))
            sections.append(cur)
            pages.append(page)
        return sections, pages

    def title(self) -> str:
        for ln in self.lines:
            m = HEADING_RE.match(ln)
            if m:
                return m.group(2).strip("* ")
        return self.name

    def locate(self, quote: str) -> Loc | None:
        """Найти цитату в документе. Точное совпадение, затем нечёткое (>=0.88) по окнам из 1–3 строк."""
        q = norm(quote)
        if len(q) < 4:
            return None
        idx = self._full.find(q)
        if idx >= 0:
            i = max(bisect.bisect_right(self._starts, idx) - 1, 0)
            return self._loc(i, True, quote.strip())
        qg, best, best_i = _grams(q), 0.0, -1
        for i in range(len(self.lines)):
            for w in (1, 2, 3):
                window = " ".join(self._norm_lines[i:i + w]).strip()
                wg = set().union(*self._grams[i:i + w])
                # shortcut: перебор окон из 1–3 строк с дешёвым предфильтром по 4-граммам; для тысяч строк
                # стоит индексировать, для типичных ТЗ (сотни строк) это мгновенно
                if not window or len(qg & wg) < 0.6 * len(qg):
                    continue
                sm = difflib.SequenceMatcher(None, q, window, autojunk=False)
                score = sum(b.size for b in sm.get_matching_blocks() if b.size >= 5) / len(q)
                if score > best:
                    best, best_i = score, i
        if best >= 0.88:
            return self._loc(best_i, False, self.lines[best_i].strip())
        return None

    def _loc(self, i: int, exact: bool, text: str) -> Loc:
        return Loc(i + 1, self._sections[i], self._pages[i], exact, text)

    def section_of(self, line_no: int) -> str:
        return self._sections[line_no - 1] if 1 <= line_no <= len(self.lines) else ""

    def chunks(self, max_chars: int = 40000) -> list[str]:
        """Делит текст по границам заголовков на куски не больше max_chars (для очень длинных документов)."""
        if len(self.text) <= max_chars:
            return [self.text]
        parts, cur = [], []
        size = 0
        for ln in self.lines:
            if HEADING_RE.match(ln) and size > max_chars * 0.6:
                parts.append("\n".join(cur))
                cur, size = [], 0
            cur.append(ln)
            size += len(ln) + 1
        if cur:
            parts.append("\n".join(cur))
        return parts


def _md_table(rows: list[list]) -> str:
    rows = [[(c or "").replace("\n", " ").replace("|", "/").strip() for c in r] for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _read_pdf(path: Path) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]

            def in_table(o):  # центр символа внутри рамки таблицы (outside_bbox режет и соседний текст)
                cx, cy = (o["x0"] + o["x1"]) / 2, (o["top"] + o["bottom"]) / 2
                return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes)

            body = page.filter(lambda o: o.get("object_type") != "char" or not in_table(o)) if boxes else page
            text = (body.extract_text() or "").strip()
            # shortcut: таблицы кладём после текста страницы, их порядок относительно текста теряется
            chunks = [f"<!-- стр. {n} -->", text] + [_md_table(t.extract()) for t in tables]
            pages.append("\n\n".join(c for c in chunks if c))
    text = "\n\n".join(pages)
    if len(re.sub(r"<!--.*?-->|\s", "", text)) < 20:
        raise ValueError("В PDF не найден текстовый слой (возможно, это скан). OCR не поддерживается.")
    return text


def _read_docx(path: Path) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d, out = docx.Document(str(path)), []
    for el in d.element.body.iterchildren():
        if el.tag.endswith("}p"):
            p = Paragraph(el, d)
            t = p.text.strip()
            if not t:
                continue
            m = re.match(r"Heading (\d)", p.style.name or "")
            out.append(("#" * int(m.group(1)) + " " + t) if m else t)
        elif el.tag.endswith("}tbl"):
            out.append(_md_table([[c.text for c in r.cells] for r in Table(el, d).rows]))
    return "\n\n".join(out)


def load_document(path: str) -> Document:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    ext = p.suffix.lower()
    if ext in (".md", ".markdown", ".txt"):
        text = p.read_text(encoding="utf-8-sig")
    elif ext == ".pdf":
        text = _read_pdf(p)
    elif ext == ".docx":
        text = _read_docx(p)
    else:
        raise ValueError(f"Формат {ext or '(без расширения)'} не поддерживается. Допустимо: .md, .txt, .pdf, .docx")
    if not text.strip():
        raise ValueError("Документ пустой.")
    return Document(text, p.name)
