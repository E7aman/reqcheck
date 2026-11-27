import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

from . import config
from .document import load_document
from .llm import CachedLLM, GeminiLLM, LLMError
from .pipeline import Pipeline
from .report import render


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m validator", description="AI-агент проверки качества требований")
    p.add_argument("input", help="файл с требованиями (.md, .txt, .pdf, .docx)")
    p.add_argument("output", help="куда записать отчёт (.md)")
    p.add_argument("--model", help=f"модель Gemini (по умолчанию GEMINI_MODEL или {config.DEFAULT_MODEL})")
    p.add_argument("--json", metavar="PATH", help="дополнительно сохранить результат в JSON (для evaluate)")
    p.add_argument("--lint-only", action="store_true", help="только детерминированные проверки, без LLM и ключа")
    p.add_argument("--no-verify", action="store_true", help="пропустить этап самопроверки находок")
    p.add_argument("--no-cache", action="store_true", help="не использовать кеш ответов модели")
    p.add_argument("--min-interval", type=float, help="минимальная пауза между запросами, с (лимиты бесплатного тарифа)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config.load_env()
    try:
        doc = load_document(args.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Ошибка чтения документа: {e}", file=sys.stderr)
        return 2

    llm, model = None, "—"
    if not args.lint_only:
        key = config.api_key()
        if not key:
            print("Ошибка: не задан GEMINI_API_KEY. Скопируйте .env.example в .env и впишите ключ "
                  "(или запустите с --lint-only).", file=sys.stderr)
            return 2
        model = args.model or os.environ.get("GEMINI_MODEL") or config.DEFAULT_MODEL
        interval = args.min_interval if args.min_interval is not None else float(os.environ.get("LLM_MIN_INTERVAL", 4))
        try:
            llm = GeminiLLM(key, model, interval)
        except ImportError:
            print("Ошибка: не установлен google-genai. Выполните: pip install -r requirements.txt", file=sys.stderr)
            return 2
        if not args.no_cache:
            llm = CachedLLM(llm, model)

    print(f"Проверяю «{doc.name}»…", file=sys.stderr)
    try:
        res = Pipeline(doc, llm, model, verify=not args.no_verify).run()
    except LLMError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 3
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(dataclasses.asdict(res), ensure_ascii=False, indent=1), encoding="utf-8")
    sev = {s: sum(f.severity == s for f in res.findings) for s in ("critical", "major", "minor")}
    print(f"Готово: {out}. Замечаний: {len(res.findings)} (критичных {sev['critical']}, "
          f"существенных {sev['major']}, незначительных {sev['minor']}).", file=sys.stderr)
    return 0
