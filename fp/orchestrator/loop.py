"""Loop orchestrator LLM tahap 1 (PRD §13.4). Pemilik: David (B).

LLM (Qwen3 lokal lewat llama-server) memanggil tool Designer, Guardian, dan Scout, lalu mengakhiri dengan
JSON ringkasan. Loop ini tidak memvalidasi ringkasan; validasi angka dan klaim (§13.5) dijalankan backend
di tahap 2 setelah semua hasil tool lengkap. Timeout, error API, atau JSON tidak valid → `degraded`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fp.config import Settings, get_settings

from .client import make_openai_client
from .prompts import SYSTEM_PROMPT, user_message
from .tools import TOOL_DEFINITIONS, ToolBox, dump_result, execute_tool

Emit = Callable[..., Any]

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
MIN_CALL_TIMEOUT_S = 3.0
FINAL_RESERVE_S = 15.0
FINAL_NUDGE = "Batas langkah hampir habis. Jangan panggil tool lagi. Akhiri sekarang dengan JSON saja sesuai format."


@dataclass
class OrchestratorResult:
    llm_status: str
    summaries: dict[str, str] = field(default_factory=dict)
    recommendation: Optional[str] = None
    error: Optional[str] = None
    steps: int = 0
    stub: bool = False


def parse_final_json(content: str) -> dict[str, Any]:
    text = THINK_RE.sub("", content or "").strip()
    fenced = FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("balasan akhir tidak berisi JSON")
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("summaries", []), list):
        raise ValueError("JSON akhir tidak sesuai format")
    return data


def _summaries(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in data.get("summaries") or []:
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str) and isinstance(item.get("text"), str):
            out[item["candidate_id"]] = item["text"].strip()
    return out


def _assistant_message(msg: Any) -> dict[str, Any]:
    calls = []
    for tc in msg.tool_calls or []:
        calls.append(
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
        )
    return {"role": "assistant", "content": msg.content or "", "tool_calls": calls}


def run_orchestrated(
    toolbox: ToolBox,
    brief_name: str,
    specs: dict[str, Any],
    n: int,
    settings: Optional[Settings] = None,
    emit: Optional[Emit] = None,
    client: Any = None,
) -> OrchestratorResult:
    s = settings or get_settings()
    say = emit or (lambda *a, **k: None)
    started = time.monotonic()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message(brief_name, specs, n)},
    ]

    def degraded(reason: str, step: int) -> OrchestratorResult:
        say("orchestrator", "error", "failed", {"step": step, "error": reason[:300]})
        return OrchestratorResult(llm_status="degraded", error=reason, steps=step)

    try:
        llm = client or make_openai_client(s)
    except Exception as exc:
        return degraded(f"klien LLM gagal dibuat: {exc}", 0)

    for step in range(1, s.orch_max_steps + 1):
        remaining = s.orch_total_timeout_s - (time.monotonic() - started)
        if remaining < MIN_CALL_TIMEOUT_S:
            return degraded(f"batas waktu total {s.orch_total_timeout_s:.0f} detik habis", step - 1)
        final = step == s.orch_max_steps or remaining < FINAL_RESERVE_S
        if final:
            messages.append({"role": "user", "content": FINAL_NUDGE})
        call_started = time.monotonic()
        try:
            response = llm.chat.completions.create(
                model=s.llm_model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="none" if final else "auto",
                parallel_tool_calls=True,
                temperature=s.llm_temperature,
                timeout=min(s.llm_timeout_s, remaining),
            )
            message = response.choices[0].message
            finish = getattr(response.choices[0], "finish_reason", None)
        except Exception as exc:
            return degraded(f"{type(exc).__name__}: {exc}", step)
        tool_calls = [] if final else list(message.tool_calls or [])
        say(
            "orchestrator",
            "llm_step",
            "done",
            {"step": step, "tool_calls": len(tool_calls), "finish_reason": finish, "final": final},
            int((time.monotonic() - call_started) * 1000),
        )
        if tool_calls:
            messages.append(_assistant_message(message))
            for tc in tool_calls:
                result = execute_tool(toolbox, tc.function.name, tc.function.arguments, n, emit)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": dump_result(result)})
            continue
        try:
            data = parse_final_json(message.content or "")
        except (ValueError, json.JSONDecodeError) as exc:
            return degraded(f"JSON akhir tidak valid: {exc}", step)
        rec = data.get("recommendation")
        return OrchestratorResult(
            llm_status="ok",
            summaries=_summaries(data),
            recommendation=rec.strip() if isinstance(rec, str) and rec.strip() else None,
            steps=step,
        )
    return degraded(f"melebihi {s.orch_max_steps} langkah tanpa jawaban akhir", s.orch_max_steps)
