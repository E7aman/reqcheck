from dataclasses import dataclass, field

from .document import Loc


@dataclass
class Item:
    rid: str                 # ID в отчёте: R-001
    doc_id: str | None       # ID в документе: Ф-1 (если есть)
    kind: str                # functional|nonfunctional|data|interface|constraint|acceptance
    quote: str
    summary: str
    loc: Loc | None = None


@dataclass
class Finding:
    scope: str               # item | set | structure
    criterion: str           # ключ из criteria.CRITERIA
    severity: str            # critical | major | minor
    quotes: list[str]
    problem: str
    fix: str = ""
    targets: list[str] = field(default_factory=list)   # rid затронутых требований
    source: str = "llm"      # llm | lint | derived
    locs: list[Loc] = field(default_factory=list)
    fid: str = ""


@dataclass
class Result:
    doc_name: str
    doc_title: str
    model: str
    version: str
    started: str
    items: list[Item] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)   # rid -> rid приёмочных критериев
    summary: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)                      # служебные счётчики прогона
