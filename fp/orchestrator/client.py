"""Klien llama-server lokal dan cek kesehatannya (PRD §13.1). Pemilik: David (B)."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from fp.config import Settings, get_settings

HEALTH_TIMEOUT_S = 3.0
HEALTH_TTL_S = 15.0


class LlmHealth:
    """`GET {LLM_BASE_URL}/models`, timeout 3 detik, hasil di-cache 15 detik."""

    def __init__(self, base_url: str, ttl_s: float = HEALTH_TTL_S, timeout_s: float = HEALTH_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_s = ttl_s
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._checked_at = 0.0
        self._ready = False
        self.last_error: Optional[str] = None

    def _probe(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/models", timeout=self.timeout_s) as resp:
                ok = 200 <= resp.status < 300
            self.last_error = None if ok else f"HTTP {resp.status}"
            return ok
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.last_error = str(getattr(exc, "reason", exc))
            return False

    def ready(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._checked_at < self.ttl_s:
            return self._ready
        with self._lock:
            if force or time.monotonic() - self._checked_at >= self.ttl_s:
                self._ready = self._probe()
                self._checked_at = time.monotonic()
        return self._ready

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self._ready = False
            self.last_error = error
            self._checked_at = time.monotonic()


def make_openai_client(settings: Optional[Settings] = None) -> Any:
    from openai import OpenAI

    s = settings or get_settings()
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=s.llm_timeout_s, max_retries=0)
