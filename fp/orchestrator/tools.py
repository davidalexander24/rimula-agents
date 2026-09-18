"""Definisi tool orchestrator dan eksekusinya (PRD §13.2). Pemilik: David (B).

Backend (`backend/app/services/pipeline.py`) mengimplementasikan `ToolBox`; orchestrator hanya
merujuk `candidate_id` dan tidak pernah mengetik ulang komposisi.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator

MAX_RESULT_CHARS = 4000
MAX_QUERY_CHARS = 200
N_MIN, N_MAX = 1, 5


class ToolBox(Protocol):
    def designer_propose(self, n: int) -> dict[str, Any]: ...

    def designer_explain(self, candidate_id: str) -> dict[str, Any]: ...

    def guardian_check(self, candidate_id: str) -> dict[str, Any]: ...

    def scout_literature(self, candidate_id: str, query: str) -> dict[str, Any]: ...

    def scout_market(self, candidate_id: str) -> dict[str, Any]: ...


def _fn(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(properties)},
        },
    }


_CID = {"type": "string", "description": "candidate_id dari hasil designer_propose"}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _fn(
        "designer_propose",
        "Designer agent: usulkan kandidat formula yang paling mungkin memenuhi seluruh spesifikasi brief. "
        "Hasil: candidate_id, komposisi ringkas, prediksi, dan P_TARGET (peluang memenuhi seluruh spesifikasi).",
        {"n": {"type": "integer", "minimum": N_MIN, "maximum": N_MAX, "description": "jumlah kandidat"}},
    ),
    _fn(
        "designer_explain",
        "Designer agent: detail prediksi satu kandidat: interval 95% viskositas, pH, droplet, peluang stabil, biaya, ketidakpastian.",
        {"candidate_id": _CID},
    ),
    _fn(
        "guardian_check",
        "Guardian agent: periksa batas palet dan regulasi (asumsi tim), klaim, anggaran, catatan halal, ketidakpastian, "
        "dan ekstrapolasi. Hasil: status pass/review/blocked dan daftar issue.",
        {"candidate_id": _CID},
    ),
    _fn(
        "scout_literature",
        "Scout agent: cari bukti literatur ilmiah open-access (Europe PMC) yang relevan untuk kandidat.",
        {
            "candidate_id": _CID,
            "query": {"type": "string", "description": "kueri singkat bahasa Inggris, maksimal 8 kata"},
        },
    ),
    _fn(
        "scout_market",
        "Scout agent: hitung produk skincare/makeup nyata (Open Beauty Facts) yang memakai kombinasi bahan kandidat.",
        {"candidate_id": _CID},
    ),
]

TOOL_NAMES = tuple(t["function"]["name"] for t in TOOL_DEFINITIONS)


class ProposeArgs(BaseModel):
    n: int

    @field_validator("n", mode="before")
    @classmethod
    def clip_n(cls, v: Any) -> int:
        return max(N_MIN, min(N_MAX, int(v)))


class CandidateArgs(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=64)


class LiteratureArgs(CandidateArgs):
    query: str = Field(min_length=1)

    @field_validator("query")
    @classmethod
    def cut_query(cls, v: str) -> str:
        return v.strip()[:MAX_QUERY_CHARS]


def dump_result(result: Any) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps({"truncated": True, "preview": text[: MAX_RESULT_CHARS - 60]}, ensure_ascii=False)


def execute_tool(
    toolbox: ToolBox,
    name: str,
    raw_arguments: Optional[str],
    run_n: int,
    emit: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Validasi argumen lalu jalankan tool. Kesalahan dikembalikan ke LLM sebagai `{"error": ...}`."""
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("argumen harus objek JSON")
    except (json.JSONDecodeError, ValueError) as exc:
        return {"error": f"argumen tidak valid: {exc}"}
    try:
        if name == "designer_propose":
            parsed = ProposeArgs.model_validate(args)
            if parsed.n != run_n and emit is not None:
                emit("system", "policy_override", "done", {"tool": name, "requested_n": args.get("n"), "used_n": run_n})
            return toolbox.designer_propose(run_n)
        if name == "designer_explain":
            return toolbox.designer_explain(CandidateArgs.model_validate(args).candidate_id)
        if name == "guardian_check":
            return toolbox.guardian_check(CandidateArgs.model_validate(args).candidate_id)
        if name == "scout_market":
            return toolbox.scout_market(CandidateArgs.model_validate(args).candidate_id)
        if name == "scout_literature":
            parsed = LiteratureArgs.model_validate(args)
            return toolbox.scout_literature(parsed.candidate_id, parsed.query)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        return {"error": f"argumen tidak valid: {'.'.join(str(p) for p in first.get('loc', ()))} {first.get('msg', '')}".strip()}
    except (TypeError, ValueError) as exc:
        return {"error": f"argumen tidak valid: {exc}"}
    except Exception as exc:
        if str(exc) == "unknown candidate_id":
            return {"error": "unknown candidate_id"}
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"error": f"tool tidak dikenal: {name}"}
