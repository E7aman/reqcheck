"""Конвейер: нарезка -> проверка требований -> проходы по набору -> покрытие -> самопроверка -> итог."""
import difflib
import subprocess
import sys
from datetime import datetime

from . import __version__, prompts
from .criteria import CRITERIA, SEVERITIES
from .document import Document, norm
from .lint import run_lint
from .llm import LLMError, LLMFatalError, LLMQuotaError
from .models import Finding, Item, Result

BATCH = 20          # больше требований в одном запросе: меньше запросов на прогон (лимиты бесплатного тарифа)
VERIFY_BATCH = 30
MAX_DOC_CHARS = 150_000
KINDS = {"functional", "nonfunctional", "data", "interface", "constraint", "acceptance"}
COVERED_KINDS = {"functional", "nonfunctional"}
SEV_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


def _str(x) -> str:
    """Ответ модели не гарантирует типы: всё, что не строка, считаем пустой строкой."""
    return x.strip() if isinstance(x, str) else ""


def _list(x) -> list:
    return x if isinstance(x, list) else []


def _short(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def agent_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        if sha.returncode == 0 and sha.stdout.strip():
            return f"{__version__} ({sha.stdout.strip()})"
    except Exception:
        pass
    return __version__


class Pipeline:
    def __init__(self, doc: Document, llm=None, model: str = "—", verify: bool = True, log=None):
        self.doc, self.llm, self.model, self.do_verify = doc, llm, model, verify
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.res = Result(doc.name, doc.title(), model if llm else "— (режим без LLM)", agent_version(),
                          datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.stats = self.res.stats = {"dropped_items": 0, "dropped_ungrounded": 0, "dropped_by_verify": 0,
                                       "failed_stages": [], "unchecked": [], "llm_calls": 0}
        self.doc_text = doc.text[:MAX_DOC_CHARS]

    # ---------- вспомогательное ----------
    def _call(self, stage: str, prompt: str):
        if self.stats.get("llm_stopped"):
            self.stats["failed_stages"].append(f"{stage} (пропущен)")
            return None
        self.log(f"  • {stage}")
        try:
            return self.llm.complete_json(stage, prompts.SYSTEM, prompt)
        except LLMFatalError:
            raise
        except LLMQuotaError as e:
            self.log(f"  ! этап «{stage}» не выполнен: {e}")
            self.stats["failed_stages"].append(stage)
            self.stats["quota_exhausted"] = self.stats["llm_stopped"] = True
            return None
        except LLMError as e:
            self.log(f"  ! этап «{stage}» не выполнен: {e}")
            self.stats["failed_stages"].append(stage)
            return None

    def _ground(self, quotes) -> list:
        locs = []
        for q in quotes:
            if isinstance(q, str) and (loc := self.doc.locate(q)):
                locs.append(loc)
        return locs

    def _make(self, raw: dict, scope: str, default_criterion: str, min_quotes: int = 1, fallback: Item | None = None,
              source: str = "llm") -> Finding | None:
        if not isinstance(raw, dict):
            return None
        quotes = _list(raw.get("quotes")) or ([raw["quote"]] if isinstance(raw.get("quote"), str) else [])
        quotes = [q for q in quotes if isinstance(q, str)]
        locs = self._ground(quotes)
        good = [q for q in quotes if self.doc.locate(q)]
        if len(locs) < min_quotes:
            if fallback and fallback.loc:
                good, locs = [fallback.quote], [fallback.loc]
            else:
                self.stats["dropped_ungrounded"] += 1
                return None
        crit, sev = raw.get("criterion"), raw.get("severity")
        crit = crit if isinstance(crit, str) and crit in CRITERIA else default_criterion
        sev = sev if isinstance(sev, str) and sev in SEVERITIES else "major"
        problem = _str(raw.get("problem"))
        if not problem:
            return None
        ids = [i for i in _list(raw.get("ids")) if isinstance(i, str) and i in self._rids]
        if fallback:
            ids = [fallback.rid]
        return Finding(scope, crit, sev, good, problem, _str(raw.get("fix")), ids, source, locs)

    # ---------- этапы ----------
    def segment(self):
        chunks = self.doc.chunks()
        raw_items = []
        for n, ch in enumerate(chunks, 1):
            r = self._call(f"нарезка требований {n}/{len(chunks)}", prompts.segment(ch, n, len(chunks)))
            raw_items += _list(r.get("items")) if isinstance(r, dict) else _list(r)
        seen, found = set(), []
        for it in raw_items:
            q = _str(it.get("quote")) if isinstance(it, dict) else ""
            if not q or norm(q) in seen:
                continue
            loc = self.doc.locate(q)
            if not loc:  # цитата не найдена в документе: элемент выдуман или искажён
                self.stats["dropped_items"] += 1
                continue
            seen.add(norm(q))
            kind = it.get("kind") if isinstance(it.get("kind"), str) and it.get("kind") in KINDS else "functional"
            found.append((loc.line, q, _str(it.get("doc_id")) or None, kind, _str(it.get("summary")) or q[:80], loc))
        found.sort(key=lambda x: x[0])
        self.res.items = [Item(f"R-{n:03d}", d, k, q, s, loc) for n, (_, q, d, k, s, loc) in enumerate(found, 1)]
        self._rids = {i.rid for i in self.res.items}
        self.log(f"    выделено элементов: {len(self.res.items)}")

    def _dicts(self, items):
        return [{"rid": i.rid, "doc_id": i.doc_id, "kind": i.kind, "quote": i.quote, "summary": i.summary}
                for i in items]

    def check_items(self):
        todo = [i for i in self.res.items if i.kind != "acceptance"]
        by_rid = {i.rid: i for i in todo}
        checked = set()
        for n in range(0, len(todo), BATCH):
            batch = todo[n:n + BATCH]
            r = self._call(f"проверка требований {n // BATCH + 1}/{-(-len(todo) // BATCH)}",
                           prompts.check_items(self.doc_text, self._dicts(batch)))
            for res in _list(r.get("results")) if isinstance(r, dict) else []:
                rid = res.get("id") if isinstance(res, dict) else None
                item = by_rid.get(rid) if isinstance(rid, str) else None
                if not item:
                    continue
                checked.add(item.rid)
                for v in _list(res.get("violations")):
                    f = self._make(v, "item", "unambiguous", fallback=item)
                    if f:
                        self.res.findings.append(f)
        self.stats["unchecked"] = [i.rid for i in todo if i.rid not in checked]

    def set_checks(self):
        items = self._dicts(self.res.items)
        for stage, build, crit, minq in (("противоречия", prompts.consistency, "consistent", 2),
                                         ("пропуски", prompts.completeness, "complete", 1),
                                         ("сверка частей и интерфейсов", prompts.crossref, "consistent", 1)):
            r = self._call(stage, build(self.doc_text, items))
            for raw in _list(r.get("findings")) if isinstance(r, dict) else []:
                f = self._make(raw, "set", crit, min_quotes=minq)
                if f:
                    self.res.findings.append(f)

    def coverage(self):
        targets = [i for i in self.res.items if i.kind in COVERED_KINDS]
        tests = [i for i in self.res.items if i.kind == "acceptance"]
        if not targets or not tests:
            return
        r = self._call("покрытие критериями приёмки", prompts.coverage(self._dicts(targets), self._dicts(tests)))
        if not isinstance(r, dict):
            return
        test_ids = {t.rid for t in tests}
        target_ids = {t.rid for t in targets}
        for c in _list(r.get("coverage")):
            if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"] in target_ids:
                self.res.coverage[c["id"]] = [x for x in _list(c.get("covered_by")) if isinstance(x, str) and x in test_ids]
        for t in targets:
            if t.rid in self.res.coverage and not self.res.coverage[t.rid]:
                sev = "major" if t.kind == "functional" else "minor"
                self.res.findings.append(Finding(
                    "set", "verifiable", sev, [t.quote],
                    f"Ни один критерий приёмки не проверяет это требование"
                    f"{f' ({t.doc_id})' if t.doc_id else ''}: правило нельзя считать подтверждаемым тестом.",
                    "Добавить сценарий приёмки: исходные условия, действие, ожидаемый результат (включая граничные случаи).",
                    [t.rid], "derived", [t.loc] if t.loc else []))

    def dedupe(self):
        """Убирает повторы: структурные находки всегда сохраняются; остальные отбрасываются, если на той же строке
        есть находка того же критерия с похожим текстом (или она структурная)."""
        kept = [f for f in self.res.findings if f.source == "lint"]
        rest = sorted((f for f in self.res.findings if f.source != "lint"), key=lambda f: SEV_ORDER[f.severity])
        for f in rest:
            lines = {l.line for l in f.locs}
            dup = False
            for k in kept:
                if k.criterion != f.criterion or (k.source == "derived") != (f.source == "derived"):
                    continue
                if not lines & {l.line for l in k.locs}:
                    continue
                if k.source == "lint" or difflib.SequenceMatcher(None, k.problem.lower(), f.problem.lower()).ratio() >= 0.6:
                    dup = True
                    break
            if not dup:
                kept.append(f)
        self.res.findings = kept

    def verify(self):
        cand = [f for f in self.res.findings if f.source != "lint"]
        for n, f in enumerate(cand, 1):
            f.fid = f"T{n}"
        drop = set()
        for n in range(0, len(cand), VERIFY_BATCH):
            batch = [{"id": f.fid, "criterion": f.criterion, "quotes": f.quotes, "problem": f.problem}
                     for f in cand[n:n + VERIFY_BATCH]]
            r = self._call(f"самопроверка находок {n // VERIFY_BATCH + 1}/{-(-len(cand) // VERIFY_BATCH)}",
                           prompts.verify(self.doc_text, batch))
            for v in _list(r.get("verdicts")) if isinstance(r, dict) else []:
                if isinstance(v, dict) and v.get("valid") is False and isinstance(v.get("id"), str):
                    drop.add(v["id"])
        self.stats["dropped_by_verify"] = len(drop)
        self.res.findings = [f for f in self.res.findings if f.fid not in drop]

    def finalize(self):
        self.res.findings.sort(key=lambda f: (SEV_ORDER[f.severity], f.locs[0].line if f.locs else 0))
        for n, f in enumerate(self.res.findings, 1):
            f.fid = f"F-{n:03d}"
        c = {s: sum(f.severity == s for f in self.res.findings) for s in SEVERITIES}
        crit = c["critical"]
        top = [f for f in self.res.findings if f.severity in ("critical", "major")][:8]
        if not self.llm:
            top = [f for f in self.res.findings][:5]
        # вывод «можно начинать» возможен только после полного анализа; при пропущенных этапах crit == 0 ничего не значит
        unchecked = len(self.stats["unchecked"])
        # найденный критичный дефект запрещает старт, а «да» требует, чтобы проверены были все требования
        complete = bool(self.llm) and not self.stats["failed_stages"] and (crit > 0 or not unchecked)
        s = {"can_start": (crit == 0) if complete else None, "verdict": "", "priorities": []}
        if complete and top:
            r = self._call("итог", prompts.summary(
                self.res.doc_title,
                {"требований": len([i for i in self.res.items if i.kind != "acceptance"]), "замечаний": c},
                [{"id": f.fid, "severity": f.severity, "problem": f.problem[:200]} for f in top]))
            if isinstance(r, dict):
                # без критичных дефектов текст модели может противоречить выводу «да», поэтому берём шаблонный
                s["verdict"] = _str(r.get("verdict")) if crit else ""
                s["priorities"] = [p.strip() for p in _list(r.get("priorities")) if isinstance(p, str) and p.strip()][:6]
        if not self.llm:
            s["verdict"] = ("Режим без LLM: выполнены только структурные проверки. Смысловой анализ (противоречия, "
                            "пропуски, качество формулировок) не проводился, вывод о готовности к разработке не делается.")
        elif not complete and not self.stats["failed_stages"]:
            s["verdict"] = (f"Анализ неполный: модель не вернула результат по требованиям ({unchecked} шт.). "
                            "Вывод о готовности к разработке не делается.")
        elif not complete:
            s["verdict"] = ("Анализ неполный: не выполнены этапы (" + ", ".join(self.stats["failed_stages"]) + "). "
                            "Вывод о готовности к разработке не делается; повторите прогон, когда модель будет доступна.")
        elif not s["verdict"]:  # запасной вариант, если этап «итог» не выполнился
            s["verdict"] = ("Критичных дефектов не выявлено: разработку можно начинать, существенные замечания "
                            "устраняются параллельно." if crit == 0 else
                            f"Выявлено критичных дефектов: {crit}. Начинать разработку не следует, пока они не устранены.")
        if not s["priorities"]:
            s["priorities"] = [f"{f.fid}: {_short(f.problem, 140)}" for f in top[:5]]
        self.res.summary = s

    def run(self) -> Result:
        self._rids = set()
        self.log("• структурные проверки")
        for f in run_lint(self.doc):
            f.locs = self._ground(f.quotes)
            if f.locs:
                self.res.findings.append(f)
        if self.llm:
            self.segment()
            if not self.res.items:  # без нарезки остальные этапы бессмысленны и только тратят квоту
                self.log("  ! требования не выделены, смысловые этапы пропущены")
                self.stats["failed_stages"].append("смысловой анализ (нет нарезки)")
                self.stats["llm_stopped"] = True
        if self.llm and not self.stats.get("llm_stopped"):
            self.check_items()
            self.set_checks()
            self.coverage()
            self.dedupe()
            if self.do_verify and self.res.findings:
                self.verify()
        self.finalize()
        self.stats["llm_calls"] = getattr(self.llm, "calls", 0)
        used = getattr(self.llm, "used", None)
        if used:
            self.res.model = ", ".join(used)
        return self.res
