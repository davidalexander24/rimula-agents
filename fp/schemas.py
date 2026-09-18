"""Kontrak data FormulaPilot (PRD §14.3). Pemilik: David (B).

Dibekukan di M0. Perubahan hanya lewat request ke David (R3) dan diumumkan di grup
sebelum diterapkan. Nama model dan field mengikuti PRD persis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0"

SystemMode = Literal["live", "degraded"]
GateStatus = Literal["pass", "review", "blocked"]
Severity = Literal["error", "warning", "info"]
RunMode = Literal["explore", "replay"]
RunStatus = Literal["running", "done", "failed"]
LlmStatus = Literal["not_used", "ok", "degraded"]
EventStatus = Literal["started", "done", "failed"]
Origin = Literal["explore", "pool"]
Decision = Literal["approved", "rejected"]
LabSource = Literal["virtual_lab", "historical", "manual"]
SummarySource = Literal["llm", "template", "unavailable"]
EvidenceType = Literal["literature", "market"]
AgentName = Literal["orchestrator", "designer", "guardian", "scout", "lab", "system"]
JobKind = Literal["designer_retrain", "scout_reindex", "guardian_recheck"]
JobTrigger = Literal["manual", "schedule", "lab_result"]
JobStatus = Literal["queued", "running", "done", "failed"]

Range = tuple[float, float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def _check_range(v: Range) -> Range:
    lo, hi = v
    if not lo < hi:
        raise ValueError("min harus lebih kecil dari max")
    return v


class Specs(_Model):
    NIACINAMIDE_MIN_PCT: float = Field(ge=0, le=10)
    VISCOSITY_CP: Range
    PH: Range
    D50_UM_MAX: float = Field(gt=0)
    STABLE: bool = True
    COST_IDR_PER_KG_MAX: float = Field(gt=0)

    @field_validator("VISCOSITY_CP", "PH")
    @classmethod
    def check_range_order(cls, v: Range) -> Range:
        return _check_range(v)


class Brief(_Model):
    brief_id: str
    name: str
    description: str
    specs: Specs


class Formula(_Model):
    GLYCERIN: float
    NIACINAMIDE: float
    CETEARYL_ALCOHOL: float
    EMULSIFIER: float
    CCT: float
    DIMETHICONE: float
    XANTHAN: float
    CARBOMER: float
    NAOH: float
    PHENOXYETHANOL: float
    AQUA: float
    RPM: float
    HMIN: float
    TEMP: float


FORMULA_FIELDS: tuple[str, ...] = tuple(Formula.model_fields)
INGREDIENT_FIELDS: tuple[str, ...] = FORMULA_FIELDS[:10]
PROCESS_FIELDS: tuple[str, ...] = ("RPM", "HMIN", "TEMP")
SPEC_KEYS: tuple[str, ...] = tuple(Specs.model_fields)
SPECS_MET_KEYS: tuple[str, ...] = SPEC_KEYS + ("ALL",)
P_SPECS_KEYS: tuple[str, ...] = ("P_VISC", "P_PH", "P_D50", "P_STABLE", "DET_OK")
LAB_OUTPUT_KEYS: tuple[str, ...] = (
    "VISCOSITY_CP",
    "PH",
    "D50_UM",
    "STABILITY_INDEX",
    "STABLE",
    "COST_IDR_PER_KG",
)


class Prediction(_Model):
    VISCOSITY_CP: float
    VISCOSITY_CP_CI95: Range
    PH: float
    PH_CI95: Range
    D50_UM: float
    D50_UM_CI95: Range
    P_STABLE: float = Field(ge=0, le=1)
    COST_IDR_PER_KG: float
    P_SPECS: dict[str, float]
    P_TARGET: float = Field(ge=0, le=1)
    UNCERTAINTY: float
    model_version: str


class Issue(_Model):
    code: str
    severity: Severity
    message: str
    field: Optional[str] = None


class Gate(_Model):
    status: GateStatus
    issues: list[Issue] = Field(default_factory=list)


class Evidence(_Model):
    type: EvidenceType
    title: str
    detail: dict[str, Any] = Field(default_factory=dict)
    source: str


class Summary(_Model):
    text: Optional[str] = None
    source: SummarySource
    reason: Optional[str] = None


class LabResult(_Model):
    lab_result_id: str
    batch_index: int = Field(ge=1)
    outputs: dict[str, float]
    specs_met: dict[str, bool]
    source: LabSource
    variant: Optional[str] = None
    recorded_at: datetime
    retrained_model_version: Optional[str] = None


class Candidate(_Model):
    candidate_id: str
    run_id: str
    rank: int = Field(ge=1)
    origin: Origin
    source_record_id: Optional[str] = None
    formula: Formula
    prediction: Optional[Prediction] = None
    gate: Gate
    evidence: list[Evidence] = Field(default_factory=list)
    summary: Summary
    decision: Optional[Decision] = None
    decision_reason: Optional[str] = None
    acknowledged: bool = False
    lab_result: Optional[LabResult] = None


class AgentEvent(_Model):
    seq: int = Field(ge=1)
    agent: str
    action: str
    status: EventStatus
    detail: dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[int] = None
    ts: datetime


class Run(_Model):
    run_id: str
    run_mode: RunMode
    session_id: Optional[str] = None
    brief_id: str
    specs: Specs
    n: int
    use_orchestrator: bool
    status: RunStatus
    llm_status: LlmStatus
    model_version: str
    recommendation: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    candidates: list[Candidate] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)


class ProgressSummary(_Model):
    scope: str = Field(pattern=r"^(global|session:.+)$")
    batches: int = Field(ge=0)
    hit_at_batch: Optional[int] = None
    best_specs_met: int = Field(ge=0)
    total_specs: int = Field(ge=0)


class BatchRecord(_Model):
    batch_index: int = Field(ge=1)
    candidate_id: str
    specs_met: dict[str, bool]
    outputs: dict[str, float]


class Progress(ProgressSummary):
    """`GET /progress`: ProgressSummary + riwayat batch (§14.5)."""

    history: list[BatchRecord] = Field(default_factory=list)


class ApiError(_Model):
    code: str
    message: str
    request_id: str


T = TypeVar("T")


class Envelope(_Model, Generic[T]):
    mode: SystemMode
    data: T


class ErrorEnvelope(_Model):
    mode: SystemMode
    error: ApiError


class RunCreate(_Model):
    run_mode: RunMode = "explore"
    brief_id: str
    specs: Optional[Specs] = None
    n: int = Field(default=3, ge=1, le=5)
    use_orchestrator: bool = False
    session_id: Optional[str] = None

    @model_validator(mode="after")
    def check_session_for_replay(self) -> "RunCreate":
        if self.run_mode == "replay" and not self.session_id:
            raise ValueError("session_id wajib untuk run_mode=replay")
        return self


class RunCreated(_Model):
    run_id: str
    status: RunStatus


class RunListItem(_Model):
    run_id: str
    run_mode: RunMode
    session_id: Optional[str] = None
    brief_id: str
    n: int
    use_orchestrator: bool
    status: RunStatus
    llm_status: LlmStatus
    model_version: str
    created_at: datetime
    finished_at: Optional[datetime] = None


REASON_MIN_LEN = 5


class DecisionRequest(_Model):
    decision: Decision
    reason: str = ""
    acknowledged: bool = False


class LabTestResponse(_Model):
    """`POST /candidates/{id}/test` dan `/reveal`."""

    candidate: Candidate
    lab_result: LabResult
    progress: Progress


class ManualResultRequest(_Model):
    outputs: dict[str, float]


class ReplaySessionCreate(_Model):
    brief_id: str
    seed: Optional[int] = None


class KnownRecord(_Model):
    record_id: str
    formula: Formula
    outputs: dict[str, float]
    specs_met: dict[str, bool]


class ReplaySession(_Model):
    """`POST /replay/sessions` mengisi `seed`; `GET /replay/sessions/{id}` mengisi `progress`."""

    session_id: str
    brief_id: str
    seed: Optional[int] = None
    progress: Optional[Progress] = None
    known: list[KnownRecord] = Field(default_factory=list)
    pool_size: int = Field(ge=0)
    model_version: str


class ProgressResetRequest(_Model):
    scope: Literal["global"] = "global"


class Health(_Model):
    model_ready: bool
    model_version: Optional[str] = None
    llm_ready: bool
    scout_ready: bool
    market_ready: bool
    evaluation_ready: bool
    db_ready: bool
    instance: str
    virtual_lab_variant: str


class PaletteIngredient(_Model):
    code: str
    inci: str
    role: str
    min_pct: float
    max_pct: float
    price_idr_per_kg: float
    notes: Optional[str] = None


class ProcessParam(_Model):
    code: str
    label: str
    unit: str
    min: float
    max: float


class Palette(_Model):
    ingredients: list[PaletteIngredient]
    process: list[ProcessParam]


class ModelVersion(_Model):
    version: str
    scope: str
    n_train: int
    parent_version: Optional[str] = None
    is_active: bool
    created_at: datetime


class Job(_Model):
    job_id: str
    kind: JobKind
    trigger: JobTrigger
    status: JobStatus
    detail: dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobCreated(_Model):
    job_id: str


class AgentStatus(_Model):
    ready: bool
    last_job: Optional[Job] = None
    next_run: Optional[datetime] = None


class AgentsStatus(_Model):
    designer: AgentStatus
    guardian: AgentStatus
    scout: AgentStatus
    market: AgentStatus
    scheduler: AgentStatus


class EvaluationReport(BaseModel):
    """Bentuk minimum `artifacts/evaluation.json` (§10.8). Isi detail milik Marshal."""

    model_config = ConfigDict(extra="allow")

    generated_at: datetime
    quick: bool
    brief_id: str
    cv: dict[str, Any]
    unc_max: Optional[float] = None
    hit_rate_random: dict[str, Optional[float]]
    closed_loop: dict[str, Any]
    replay_historical: dict[str, Any]
    liposome_validation: dict[str, Any]
    savings_estimate: dict[str, Any]
    runtime_seconds: Optional[float] = None
    notes: list[str] = Field(default_factory=list)
