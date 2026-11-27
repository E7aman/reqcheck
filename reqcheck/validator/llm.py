"""Работа с моделью: Gemini, повторы, паузы под лимиты, кеш ответов, разбор JSON."""
import hashlib
import json
import re
import sys
import time
from pathlib import Path


class LLMError(RuntimeError):
    pass


class LLMFatalError(LLMError):
    """Ошибка, которую повторы не исправят (неверный ключ, снятая модель): прогон останавливается сразу."""


class LLMQuotaError(LLMError):
    """Исчерпана квота (в сутки или после всех повторов): дальнейшие вызовы бессмысленны."""


FATAL_CODES = {400, 401, 403, 404}


def _retry_delay(msg: str) -> float | None:
    m = re.search(r"'retryDelay': '(\d+(?:\.\d+)?)s'", msg) or re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
    return float(m.group(1)) if m else None


def extract_json(text: str):
    """Достаёт JSON из ответа модели, даже если он обёрнут в ```json ... ``` или с пояснением вокруг."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise ValueError("в ответе нет JSON")
    s = min(starts)
    e = max(t.rfind("}"), t.rfind("]"))
    return json.loads(t[s:e + 1])


class GeminiLLM:
    """model может быть списком через запятую: следующая модель берётся, когда у текущей снята/исчерпана квота."""

    def __init__(self, api_key: str, model: str, min_interval: float = 4.0, retries: int = 5):
        from google import genai
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.idx, self.model = 0, self.models[0]
        self.min_interval, self.retries = min_interval, retries
        self._last = 0.0
        self.calls = 0
        self.used: list[str] = []

    def _next_model(self) -> bool:
        if self.idx + 1 < len(self.models):
            self.idx += 1
            print(f"  [llm] переключаюсь на резервную модель {self.models[self.idx]}", file=sys.stderr)
            self.model = self.models[self.idx]
            return True
        return False

    def _generate(self, system: str, prompt: str) -> str:
        cfg = self._types.GenerateContentConfig(system_instruction=system, temperature=0.0,
                                                response_mime_type="application/json")
        attempt = 0
        while True:
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                self.calls += 1
                r = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                if not r.text:
                    raise LLMError("пустой ответ модели")
                if self.model not in self.used:
                    self.used.append(self.model)
                return r.text
            except Exception as e:
                code, msg = getattr(e, "code", None), str(e)
                if code in FATAL_CODES:
                    if code == 404 and self._next_model():
                        attempt = 0
                        continue
                    hint = {404: " Модель недоступна: задайте другую через GEMINI_MODEL в .env или флаг --model.",
                            401: " Проверьте GEMINI_API_KEY.", 403: " Проверьте GEMINI_API_KEY и права ключа."}.get(code, "")
                    raise LLMFatalError(f"Gemini вернул ошибку {code}, повторы не помогут.{hint}\n{msg}") from e
                daily = code == 429 and re.search(r"per ?day", msg, re.I) is not None
                if daily or attempt >= self.retries - 1:
                    if self._next_model():
                        attempt = 0
                        continue
                    if daily:
                        raise LLMQuotaError("Исчерпана суточная квота Gemini. Подождите до сброса, включите оплату, "
                                            "либо добавьте резервную модель в GEMINI_MODEL (через запятую).") from e
                    raise LLMQuotaError(f"Gemini недоступен после {self.retries} попыток: {msg}") from e
                hinted = _retry_delay(msg) if code == 429 else None
                delay = hinted + 1 if hinted and hinted <= 120 else min(10 * 2 ** attempt, 90)
                print(f"  [llm] {type(e).__name__}: повтор через {delay:.0f} с", file=sys.stderr)
                time.sleep(delay)
                attempt += 1

    def complete_json(self, stage: str, system: str, prompt: str):
        text = self._generate(system, prompt)
        try:
            return extract_json(text)
        except ValueError:
            text = self._generate(system, prompt + "\n\nВАЖНО: верни только валидный JSON, без пояснений.")
            try:
                return extract_json(text)
            except ValueError as e:
                raise LLMError(f"Модель вернула невалидный JSON на этапе «{stage}»") from e


class CachedLLM:
    """Кеш ответов на диске: повторный прогон того же документа не тратит квоту и даёт тот же результат."""

    def __init__(self, inner, model: str, cache_dir: str = ".llm_cache"):
        self.inner, self.model, self.dir = inner, model, Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0

    def complete_json(self, stage: str, system: str, prompt: str):
        key = hashlib.sha256(f"{self.model}\0{stage}\0{system}\0{prompt}".encode()).hexdigest()
        f = self.dir / f"{key}.json"
        if f.is_file():
            self.hits += 1
            return json.loads(f.read_text(encoding="utf-8"))
        res = self.inner.complete_json(stage, system, prompt)
        f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return res

    def __getattr__(self, name):
        return getattr(self.inner, name)
