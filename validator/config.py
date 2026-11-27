import os
from pathlib import Path

DEFAULT_MODEL = "gemini-3.8-flash"   # имя из подсказки API; актуальные модели и лимиты смотрите в Google AI Studio, меняется через GEMINI_MODEL


def load_env(path: str = ".env") -> None:
    """Минимальный разбор .env (без зависимостей). Уже заданные переменные окружения не перезаписываются."""
    p = Path(path)
    if not p.is_file():
        return
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
