from __future__ import annotations

import json
import os
from typing import Any

from django.conf import settings

from .prompts import GROQ_SYSTEM_RULES


class GroqJSONClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
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
        messages = [
            {"role": "system", "content": GROQ_SYSTEM_RULES},
            {"role": "user", "content": f"{task}\n\nJSON input:\n{compact_payload}"},
        ]
        try:
            client = Groq(api_key=self.api_key)
            completion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception:
            return None
        content = completion.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
