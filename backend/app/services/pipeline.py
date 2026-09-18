"""Pipeline satu run: Designer → Guardian → Scout market & literatur → ringkasan (PRD §13.2, §13.4). Pemilik: David (B).

`Pipeline` adalah implementasi `fp.orchestrator.tools.ToolBox`. Jalur tanpa LLM memanggil `enforce_policy()`
langsung; jalur orchestrator memanggil tool yang sama lewat LLM, lalu `enforce_policy()` menutup langkah
yang terlewat. Hasil modul milik anggota lain dinormalisasi ke `fp.schemas` di sini.
"""

from __future__ import annotations

import inspect
import logging
import math
import time
from typing import Any, Callable, Optional

from fp import schemas as S
from fp.io_utils import read_json, to_jsonable
from fp.orchestrator import templates
from fp.orchestrator.validate import collect_numbers, validate_text

from .. import repo
from ..state import AppState, optional_module
from . import training

log = logging.getLogger("formulapilot.pipeline")

MARKET_MIN_PCT = 0.1
MAX_TOOL_RESULT_CHARS = 4000
MAX_QUERY_CHARS = 200
MAX_SUMMARY_CHARS = 700
LIT_PER_CANDIDATE = 3
LIT_POOL_K = 8
REJECTED_PREVIEW_CHARS = 240
TIE_DECIMALS = 3

PENDING_GATE = S.Gate(
    status="review",
    issues=[S.Issue(code="PENDING_CHECK", severity="info", message="Menunggu pemeriksaan Guardian.")],
)
PENDING_SUMMARY = S.Summary(text=None, source="unavailable", reason="pending")
GUARDIAN_ERROR_GATE = S.Gate(
    status="review",
    issues=[S.Issue(code="GUARDIAN_ERROR", severity="warning", message="Guardian gagal memeriksa kandidat ini, wajib ditinjau manual.")],
)


class ToolError(Exception):
    pass


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _prob(value: Optional[float]) -> Optional[float]:
    return None if value is None else min(max(value, 0.0), 1.0)


def _flatten_prediction(row: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    for key, value in (prediction or {}).items():
        if key.endswith("_CI95") and isinstance(value, (list, tuple)) and len(value) == 2:
            base = key[: -len("_CI95")]
            row[f"{base}_LO"], row[f"{base}_HI"] = value
        elif key == "P_SPECS" and isinstance(value, dict):
            for k, v in value.items():
                row.setdefault(k, v)
        elif key not in row:
            row[key] = value
    return row


def designer_rows(table: Any) -> list[dict[str, Any]]:
    """Normalisasi keluaran Designer menjadi baris datar (kolom formula + prediksi + P_*).

    Menerima DataFrame/list baris datar, list `{"formula", "prediction", "reason"}` (`propose`),
    atau list `(row, prediction)` (`rank_pool`).
    """
    if table is None:
        return []
    items = table.to_dict(orient="records") if hasattr(table, "to_dict") else list(table)
    rows = []
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            rows.append(_flatten_prediction(dict(item[0]), dict(item[1] or {})))
        elif isinstance(item, dict) and isinstance(item.get("formula"), dict):
            row = _flatten_prediction(dict(item["formula"]), dict(item.get("prediction") or {}))
            if item.get("reason") is not None:
                row["reason"] = item["reason"]
            rows.append(row)
        else:
            rows.append(dict(item))
    return rows


def row_to_formula(row: dict[str, Any]) -> S.Formula:
    values: dict[str, float] = {}
    for key in S.FORMULA_FIELDS:
        if key == "AQUA" and _num(row.get("AQUA")) is None:
            continue
        v = _num(row.get(key))
        if v is None:
            raise ToolError(f"kolom formula {key} kosong/tidak valid")
        values[key] = v
    if "AQUA" not in values:
        values["AQUA"] = 100.0 - sum(values[k] for k in S.INGREDIENT_FIELDS)
    return S.Formula(**values)


def row_to_prediction(row: dict[str, Any], model_version: str) -> Optional[S.Prediction]:
    keys = [
        "VISCOSITY_CP", "VISCOSITY_CP_LO", "VISCOSITY_CP_HI", "PH", "PH_LO", "PH_HI",
        "D50_UM", "D50_UM_LO", "D50_UM_HI", "P_STABLE", "COST_IDR_PER_KG", "UNCERTAINTY",
        "P_VISC", "P_PH", "P_D50", "DET_OK", "P_TARGET",
    ]
    v = {k: _num(row.get(k)) for k in keys}
    if any(val is None for val in v.values()):
        return None
    return S.Prediction(
        VISCOSITY_CP=v["VISCOSITY_CP"],
        VISCOSITY_CP_CI95=(min(v["VISCOSITY_CP_LO"], v["VISCOSITY_CP_HI"]), max(v["VISCOSITY_CP_LO"], v["VISCOSITY_CP_HI"])),
        PH=v["PH"],
        PH_CI95=(min(v["PH_LO"], v["PH_HI"]), max(v["PH_LO"], v["PH_HI"])),
        D50_UM=v["D50_UM"],
        D50_UM_CI95=(min(v["D50_UM_LO"], v["D50_UM_HI"]), max(v["D50_UM_LO"], v["D50_UM_HI"])),
        P_STABLE=_prob(v["P_STABLE"]),
        COST_IDR_PER_KG=v["COST_IDR_PER_KG"],
        P_SPECS={
            "P_VISC": _prob(v["P_VISC"]),
            "P_PH": _prob(v["P_PH"]),
            "P_D50": _prob(v["P_D50"]),
            "P_STABLE": _prob(v["P_STABLE"]),
            "DET_OK": _prob(v["DET_OK"]),
        },
        P_TARGET=_prob(v["P_TARGET"]),
        UNCERTAINTY=v["UNCERTAINTY"],
        model_version=model_version,
    )


def _call_with_supported_kwargs(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def order_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Urut P_TARGET turun; bila seri sampai 3 desimal, dahulukan biaya bahan termurah.

    Pada brief yang mudah, P_TARGET semua kandidat menumpuk di batas atas (0,95 karena noise uji 5%),
    sehingga urutan Designer praktis acak. Biaya adalah pembeda deterministik yang bisa dijelaskan.
    """

    def key(row: dict[str, Any]) -> tuple[float, float]:
        p = _num(row.get("P_TARGET"))
        cost = _num(row.get("COST_IDR_PER_KG"))
        return (-round(p, TIE_DECIMALS) if p is not None else 0.0, cost if cost is not None else 0.0)

    return sorted(rows, key=key)


def _norm_query(query: str) -> str:
    return " ".join(sorted(set(query.lower().split())))


def _evidence_key(ev: S.Evidence) -> str:
    detail = ev.detail or {}
    return str(detail.get("pmcid") or detail.get("id") or detail.get("doi") or ev.title).lower()


def _truncate(obj: Any) -> dict[str, Any]:
    from fp.io_utils import dumps_json

    data = to_jsonable(obj)
    text = dumps_json(data, indent=None)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return data if isinstance(data, dict) else {"result": data}
    return {"truncated": True, "preview": text[: MAX_TOOL_RESULT_CHARS - 100]}


class Pipeline:
    def __init__(
        self,
        state: AppState,
        run: S.Run,
        designer: Any,
        seed: int,
        exclude: Optional[list[S.Formula]] = None,
        pool: Any = None,
    ) -> None:
        self.state = state
        self.run = run
        self.designer = designer
        self.seed = seed
        self.exclude = exclude or []
        self.pool = pool
        self.candidates: dict[str, S.Candidate] = {}
        self.checked: set[str] = set()
        self.market_done: set[str] = set()
        self.literature_done: set[str] = set()
        self._lit_queries: set[str] = set()
        self._lit_seen: set[str] = set()
        self._lit_reused: set[str] = set()
        self._guardian_ctx: Any = None
        self._proposed = False

    # events

    def emit(self, agent: str, action: str, status: str, detail: Optional[dict] = None, duration_ms: Optional[int] = None) -> None:
        repo.add_event(self.state.db, self.run.run_id, agent, action, status, detail, duration_ms)

    def _traced(self, agent: str, action: str, call: str, detail: dict, fn: Callable[[], Any], done: Callable[[Any], dict]) -> Any:
        self.emit(agent, action, "started", {"call": call, **detail})
        started = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:
            ms = int((time.perf_counter() - started) * 1000)
            self.emit(agent, action, "failed", {"call": call, **detail, "error": f"{type(exc).__name__}: {exc}"[:300]}, ms)
            raise
        ms = int((time.perf_counter() - started) * 1000)
        self.emit(agent, action, "done", {"call": call, **detail, **done(result)}, ms)
        return result

    def _candidate(self, candidate_id: str) -> S.Candidate:
        cand = self.candidates.get(candidate_id)
        if cand is None:
            raise ToolError("unknown candidate_id")
        return cand

    def _save(self, cand: S.Candidate, **fields: Any) -> S.Candidate:
        updated = cand.model_copy(update=fields)
        self.candidates[cand.candidate_id] = updated
        repo.update_candidate(self.state.db, cand.candidate_id, **fields)
        return updated

    # tools

    def designer_propose(self, n: int) -> dict[str, Any]:
        if not self._proposed:
            self._traced(
                "designer",
                "propose",
                "designer_propose#1",
                {"n": n, "seed": self.seed},
                lambda: self._propose(n),
                lambda cands: {
                    "candidate_ids": [c.candidate_id for c in cands],
                    "model_version": self.run.model_version,
                    "STUB": bool(getattr(self.designer, "is_stub", False)),
                },
            )
            self._proposed = True
        return {"candidates": [self._brief_view(c) for c in self.candidates.values()]}

    def _propose(self, n: int) -> list[S.Candidate]:
        specs = self.run.specs.model_dump(mode="json")
        exclude_df = None
        if self.exclude:
            import pandas as pd

            exclude_df = pd.DataFrame([f.model_dump() for f in self.exclude])
        if self.pool is not None:
            if len(self.pool) == 0:
                raise ToolError("Pool data historis sesi ini sudah habis")
            table = _call_with_supported_kwargs(self.designer.rank_pool, self.pool, specs, n=n)
        else:
            kwargs: dict[str, Any] = {"n": n, "seed": self.seed, "exclude": exclude_df}
            if self.state.settings.designer_n_samples:
                kwargs["n_samples"] = self.state.settings.designer_n_samples
            table = _call_with_supported_kwargs(self.designer.propose, specs, **kwargs)
        rows = order_candidates(designer_rows(table)[:n])
        if not rows:
            raise ToolError("Designer tidak mengusulkan kandidat")
        out = []
        for rank, row in enumerate(rows, start=1):
            cand = S.Candidate(
                candidate_id=repo.new_id("cand"),
                run_id=self.run.run_id,
                rank=rank,
                origin="pool" if self.pool is not None else "explore",
                source_record_id=str(row["record_id"]) if self.pool is not None and row.get("record_id") is not None else None,
                formula=row_to_formula(row),
                prediction=row_to_prediction(row, self.run.model_version),
                gate=PENDING_GATE,
                summary=PENDING_SUMMARY,
            )
            repo.insert_candidate(self.state.db, cand)
            self.candidates[cand.candidate_id] = cand
            out.append(cand)
        return out

    def designer_explain(self, candidate_id: str) -> dict[str, Any]:
        cand = self._candidate(candidate_id)
        return _truncate(
            {"candidate_id": candidate_id, "prediction": cand.prediction, "formula": cand.formula, "rank": cand.rank}
        )

    def guardian_check(self, candidate_id: str) -> dict[str, Any]:
        cand = self._candidate(candidate_id)
        if candidate_id not in self.checked:
            try:
                gate = self._traced(
                    "guardian",
                    "check",
                    f"guardian_check#{candidate_id}",
                    {"candidate_id": candidate_id},
                    lambda: self._check(cand),
                    lambda g: {"status": g.status, "n_issues": len(g.issues)},
                )
            except Exception as exc:
                log.warning("guardian gagal untuk %s: %s", candidate_id, exc)
                gate = GUARDIAN_ERROR_GATE
            cand = self._save(cand, gate=gate)
            self.checked.add(candidate_id)
        return _truncate({"candidate_id": candidate_id, "gate": cand.gate})

    def _guardian_context(self, module: Any) -> Any:
        if self._guardian_ctx is not None:
            return self._guardian_ctx
        palette, _ = optional_module("fp.palette")
        bounds = None
        if palette is not None and hasattr(palette, "bounds"):
            try:
                bounds = palette.bounds()
            except Exception as exc:
                log.warning("palette.bounds() gagal: %s", exc)
        market_stats = None
        market, _ = optional_module("fp.market")
        if market is not None and self.state.optional_status("fp.market").get("ready"):
            if hasattr(market, "stats"):
                market_stats = market.stats()
            else:
                market_stats = read_json(self.state.settings.ingredient_stats_json, default=None)
        kwargs = dict(
            specs=self.run.specs,
            bounds=bounds,
            regulatory=None,
            unc_max=self.state.unc_max(),
            train_X_scaled=training.scaled_training_features(self.state, self.run.model_version, self.designer),
            scaler=getattr(self.designer, "scaler", None),
            nn_threshold=None,
            market=market_stats,
        )
        builder = getattr(module, "build_context", None) or module.GuardianContext
        if builder is module.GuardianContext:
            kwargs["specs"] = self.run.specs.model_dump(mode="json")
        self._guardian_ctx = _call_with_supported_kwargs(builder, **kwargs)
        return self._guardian_ctx

    def _check(self, cand: S.Candidate) -> S.Gate:
        module, err = optional_module("fp.guardian")
        if module is None:
            return S.Gate(
                status="review",
                issues=[S.Issue(code="GUARDIAN_UNAVAILABLE", severity="warning", message="Guardian belum tersedia, wajib ditinjau manual.")],
            )
        ctx = self._guardian_context(module)
        prediction = cand.prediction.model_dump(mode="json") if cand.prediction else None
        result = module.check(cand.formula.model_dump(), prediction, ctx)
        return S.Gate.model_validate(to_jsonable(result))

    def scout_market(self, candidate_id: str) -> dict[str, Any]:
        cand = self._candidate(candidate_id)
        if candidate_id in self.market_done:
            return _truncate({"candidate_id": candidate_id, "evidence": [e for e in cand.evidence if e.type == "market"]})
        if not self.state.optional_status("fp.market").get("ready"):
            self.market_done.add(candidate_id)
            return {"candidate_id": candidate_id, "evidence": [], "reason": "market_not_ready"}
        try:
            evidence = self._traced(
                "scout",
                "market",
                f"scout_market#{candidate_id}",
                {"candidate_id": candidate_id},
                lambda: self._market(cand),
                lambda ev: {"n_products_all": ev.detail.get("n_products_all") if ev else None},
            )
        except Exception as exc:
            log.warning("market gagal untuk %s: %s", candidate_id, exc)
            evidence = None
        self.market_done.add(candidate_id)
        if evidence is not None:
            cand = self._save(cand, evidence=[*cand.evidence, evidence])
        return _truncate({"candidate_id": candidate_id, "evidence": [evidence] if evidence else []})

    def _market(self, cand: S.Candidate) -> Optional[S.Evidence]:
        module, _ = optional_module("fp.market")
        if hasattr(module, "codes_for"):
            codes = module.codes_for(cand.formula)
        else:
            codes = [k for k in S.INGREDIENT_FIELDS if getattr(cand.formula, k) >= MARKET_MIN_PCT]
        result = to_jsonable(module.support(codes)) or {}
        if result.get("reason") or result.get("STUB") or result.get("n_products_all") is None:
            return None
        if hasattr(module, "evidence"):
            ev = module.evidence(result)
            return S.Evidence.model_validate(to_jsonable(ev)) if ev is not None else None
        detail = {k: v for k, v in result.items() if k != "type"}
        return S.Evidence(
            type="market",
            title=templates.market_title(int(result["n_products_all"]), int(result.get("n_indonesia") or 0)),
            detail=detail,
            source="Open Beauty Facts",
        )

    def scout_literature(self, candidate_id: str, query: Optional[str] = None) -> dict[str, Any]:
        cand = self._candidate(candidate_id)
        if candidate_id in self.literature_done:
            return _truncate({"candidate_id": candidate_id, "evidence": [e for e in cand.evidence if e.type == "literature"]})
        if not self.state.optional_status("fp.scout").get("ready"):
            self.literature_done.add(candidate_id)
            return {"candidate_id": candidate_id, "evidence": [], "reason": "scout_index_missing"}
        module, _ = optional_module("fp.scout")
        q, source = self._literature_query(module, cand, query)
        try:
            evidence = self._traced(
                "scout",
                "literature",
                f"scout_literature#{candidate_id}",
                {"candidate_id": candidate_id, "query": q, "query_source": source},
                lambda: self._literature(module, q),
                lambda evs: {"n_results": len(evs), "n_reused": sum(1 for e in evs if _evidence_key(e) in self._lit_reused)},
            )
        except Exception as exc:
            log.warning("literatur gagal untuk %s: %s", candidate_id, exc)
            evidence = []
        self.literature_done.add(candidate_id)
        if evidence:
            cand = self._save(cand, evidence=[*cand.evidence, *evidence])
        return _truncate({"candidate_id": candidate_id, "evidence": evidence})

    def _literature_query(self, module: Any, cand: S.Candidate, query: Optional[str]) -> tuple[str, str]:
        """Kueri LLM dipakai bila belum dipakai kandidat lain di run ini; jika sama, pakai `scout.query_for(formula)`."""
        llm_q = (query or "").strip()[:MAX_QUERY_CHARS]
        if llm_q and _norm_query(llm_q) not in self._lit_queries:
            self._lit_queries.add(_norm_query(llm_q))
            return llm_q, "llm"
        own = (module.query_for(cand.formula.model_dump()) or "").strip()[:MAX_QUERY_CHARS] if hasattr(module, "query_for") else ""
        source = "query_for_dedup" if llm_q else "query_for"
        q = own or llm_q
        self._lit_queries.add(_norm_query(q))
        return q, source

    def _literature(self, module: Any, query: str) -> list[S.Evidence]:
        hits = []
        for item in to_jsonable(list(module.search(query, k=LIT_POOL_K) or [])):
            if not isinstance(item, dict) or item.get("STUB") or not item.get("title"):
                continue
            if hasattr(module, "evidence"):
                hits.append(S.Evidence.model_validate(to_jsonable(module.evidence(item))))
                continue
            hits.append(
                S.Evidence(
                    type="literature",
                    title=str(item["title"]),
                    detail={k: item.get(k) for k in ("id", "pmcid", "doi", "year", "journal", "url", "score", "snippet")},
                    source="Europe PMC",
                )
            )
        fresh = [e for e in hits if _evidence_key(e) not in self._lit_seen]
        chosen = (fresh + [e for e in hits if _evidence_key(e) in self._lit_seen])[:LIT_PER_CANDIDATE]
        self._lit_reused = {_evidence_key(e) for e in chosen if _evidence_key(e) in self._lit_seen}
        self._lit_seen.update(_evidence_key(e) for e in chosen)
        return chosen

    # policy enforcement (§13.4 tahap 2)

    def _enforce(self, label: str, fn: Callable[[], Any], detail: dict) -> None:
        if self.run.use_orchestrator:
            self.emit("system", "policy_enforced", "done", {"step": label, **detail})
        try:
            fn()
        except Exception as exc:
            log.warning("langkah %s gagal: %s", label, exc)

    def enforce_policy(self, llm_summaries: Optional[dict[str, str]] = None) -> None:
        if not self._proposed:
            if self.run.use_orchestrator:
                self.emit("system", "policy_enforced", "done", {"step": "designer_propose"})
            self.designer_propose(self.run.n)
        for cid in list(self.candidates):
            if cid not in self.checked:
                self._enforce("guardian_check", lambda cid=cid: self.guardian_check(cid), {"candidate_id": cid})
        for cid, cand in list(self.candidates.items()):
            if cand.gate.status == "blocked":
                continue
            if cid not in self.market_done:
                self._enforce("scout_market", lambda cid=cid: self.scout_market(cid), {"candidate_id": cid})
            if cid not in self.literature_done:
                self._enforce("scout_literature", lambda cid=cid: self.scout_literature(cid), {"candidate_id": cid})
        self.apply_summaries(llm_summaries or {})

    def allowed_numbers(self, cand: S.Candidate) -> set[float]:
        return collect_numbers(cand.formula, cand.prediction, cand.gate, cand.evidence, cand.rank, self.run.specs, self.run.n)

    def _reject(self, target: str, verdict: Any, text: str = "") -> None:
        action = {"number": "summary_rejected_number", "claim": "summary_rejected_claim"}.get(verdict.reason)
        if action:
            self.emit(
                "system", action, "done",
                {"candidate_id": target, "offending": verdict.offending[:10], "text_preview": text[:REJECTED_PREVIEW_CHARS]},
            )

    def _ranks_for_ids(self, text: str) -> str:
        for cid, cand in self.candidates.items():
            text = text.replace(f"kandidat {cid}", f"kandidat #{cand.rank}").replace(cid, f"#{cand.rank}")
        return text

    def apply_summaries(self, llm_summaries: dict[str, str]) -> None:
        accepted, rejected = [], []
        for cid, cand in list(self.candidates.items()):
            text = self._ranks_for_ids((llm_summaries.get(cid) or "").strip())[:MAX_SUMMARY_CHARS]
            reason: Optional[str] = None
            if text:
                verdict = validate_text(text, self.allowed_numbers(cand))
                if verdict.ok:
                    self._save(cand, summary=S.Summary(text=text, source="llm"))
                    accepted.append(cid)
                    continue
                self._reject(cid, verdict, text)
                rejected.append(cid)
                reason = f"rejected_{verdict.reason}"
            elif self.run.use_orchestrator:
                reason = "not_summarized_by_llm"
            if self.run.use_orchestrator:
                self.emit("system", "fallback_template", "done", {"candidate_id": cid, "reason": reason})
            self._save(cand, summary=templates.template_summary(cand, reason))
        if llm_summaries:
            self.emit("orchestrator", "summarize", "done", {"accepted": accepted, "rejected": rejected})
        elif not self.run.use_orchestrator:
            self.emit("system", "summarize", "done", {"source": "template", "n": len(self.candidates)})

    def validated_recommendation(self, text: Optional[str]) -> Optional[str]:
        text = self._ranks_for_ids((text or "").strip())[:MAX_SUMMARY_CHARS]
        if not text:
            return None
        allowed: set[float] = set()
        for cand in self.candidates.values():
            allowed |= self.allowed_numbers(cand)
        verdict = validate_text(text, allowed)
        if verdict.ok:
            return text
        self._reject("recommendation", verdict, text)
        return None

    def _brief_view(self, cand: S.Candidate) -> dict[str, Any]:
        p = cand.prediction
        return {
            "candidate_id": cand.candidate_id,
            "rank": cand.rank,
            "formula": {k: round(v, 3) for k, v in cand.formula.model_dump().items() if v},
            "prediction": None
            if p is None
            else {
                "VISCOSITY_CP": round(p.VISCOSITY_CP),
                "PH": round(p.PH, 2),
                "D50_UM": round(p.D50_UM, 2),
                "P_STABLE": round(p.P_STABLE, 2),
                "COST_IDR_PER_KG": round(p.COST_IDR_PER_KG),
                "P_TARGET": round(p.P_TARGET, 2),
            },
        }

    def recommendation(self) -> str:
        return templates.recommendation(self.candidates.values())
