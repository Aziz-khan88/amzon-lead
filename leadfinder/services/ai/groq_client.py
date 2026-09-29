from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings

from .prompts import GROQ_SYSTEM_RULES

_LOCK = threading.RLock()
_DISK_CACHE: dict[str, dict] | None = None
MAX_CACHE_ENTRIES = 2000


def _cache_path() -> Path:
    return Path(settings.BASE_DIR) / ".cache" / "groq_completions.json"


def _cache_seconds() -> int:
    return max(0, int(getattr(settings, "APP_GROQ_CACHE_SECONDS", 24 * 60 * 60)))


def _cache_key(task: str, model: str, payload: str) -> str:
    raw = json.dumps([task, model, payload], ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_disk_cache() -> dict[str, dict]:
    global _DISK_CACHE
    if _DISK_CACHE is not None:
        return _DISK_CACHE
    path = _cache_path()
    if not path.exists():
        _DISK_CACHE = {}
        return _DISK_CACHE
    try:
        _DISK_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _DISK_CACHE = {}
    return _DISK_CACHE


def _save_disk_cache(cache: dict[str, dict], ttl: int) -> None:
    now = time.time()
    # Prune expired entries, then cap the file at the newest MAX_CACHE_ENTRIES
    # so repeated runs never grow an unbounded cache file.
    pruned = {key: item for key, item in cache.items() if now - float(item.get("created_at", 0)) <= ttl}
    if len(pruned) > MAX_CACHE_ENTRIES:
        pruned = dict(
            sorted(pruned.items(), key=lambda kv: float(kv[1].get("created_at", 0)))[-MAX_CACHE_ENTRIES:]
        )
    cache.clear()
    cache.update(pruned)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)


class GroqJSONClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.max_chars = int(getattr(settings, "APP_MAX_GROQ_INPUT_CHARS", 12000))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            from groq import Groq
        except Exception:
            return None
        compact_payload = json.dumps(payload, ensure_ascii=True)[: self.max_chars]

        ttl = _cache_seconds()
        key = _cache_key(task, self.model, compact_payload)
        if ttl > 0:
            with _LOCK:
                hit = _load_disk_cache().get(key)
                if hit and time.time() - float(hit.get("created_at", 0)) <= ttl:
                    cached = hit.get("response")
                    if isinstance(cached, dict):
                        return dict(cached)

        messages = [
            {"role": "system", "content": GROQ_SYSTEM_RULES},
            {"role": "user", "content": f"{task}\n\nJSON input:\n{compact_payload}"},
        ]
        try:
            client = Groq(api_key=self.api_key, base_url="https://api.groq.com")
            completion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Groq AI completion failed: %s", exc)
            return None

        content = completion.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None

        if ttl > 0:
            with _LOCK:
                cache = _load_disk_cache()
                cache[key] = {"created_at": time.time(), "model": self.model, "task": task[:200], "response": parsed}
                try:
                    _save_disk_cache(cache, ttl)
                except Exception:
                    pass
        return parsed


def clear_groq_cache() -> None:
    """Test hook: drop cached Groq completions."""
    global _DISK_CACHE
    with _LOCK:
        _DISK_CACHE = {}
        path = _cache_path()
        if path.exists():
            path.unlink()
