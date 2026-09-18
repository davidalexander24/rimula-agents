"""Path dan konfigurasi FormulaPilot (PRD §6.4, §7.3, §13.1, §14.2). Pemilik: David (B).

Variabel instance (`INSTANCE`, `APP_PORT`, `PUBLIC_ROOT_PATH`, `FP_RUNTIME_DIR`) selalu dari
`scripts/env.sh`. `.env` hanya melengkapi variabel yang belum ada dan tidak pernah menimpa.
Pakai `get_settings()`; test yang mengubah env memanggil `get_settings(refresh=True)`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

WIB = timezone(timedelta(hours=7), name="WIB")

FP_HOME_DEFAULT = Path(__file__).resolve().parent.parent

_PROTECTED = {
    "FP_MEMBER",
    "FP_HOME",
    "INSTANCE",
    "APP_PORT",
    "FP_RUNTIME_DIR",
    "PUBLIC_ROOT_PATH",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "TOKENIZERS_PARALLELISM",
    "PYTHONPATH",
    "PATH",
    "HOME",
}


def now_wib() -> datetime:
    return datetime.now(WIB).replace(microsecond=0)


def now_iso() -> str:
    return now_wib().isoformat()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if not key.isidentifier() or key in _PROTECTED or key in os.environ:
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        os.environ[key] = val


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: Optional[float]) -> Optional[float]:
    raw = _env(name, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "").lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on"}


def _resolve(home: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (home / p)


@dataclass(frozen=True)
class Settings:
    fp_home: Path
    member: str
    instance: str
    app_port: int
    public_root_path: str
    notebook_id: str
    runtime_dir: Path
    frontend_dist: Path

    default_brief: str
    default_seed: int
    virtual_lab_variant: str
    unc_max: Optional[float]

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_s: float
    llm_temperature: float
    orch_max_steps: int
    orch_total_timeout_s: float

    scout_query_device: str
    scout_build_device: str
    scheduler_enabled: bool
    agent_warmup: bool
    designer_n_samples: Optional[int]
    run_timeout_s: float
    allowed_origins: tuple[str, ...]

    @property
    def data_dir(self) -> Path:
        return self.fp_home / "data"

    @property
    def assumptions_dir(self) -> Path:
        return self.data_dir / "assumptions"

    @property
    def ingredients_csv(self) -> Path:
        return self.assumptions_dir / "ingredients.csv"

    @property
    def briefs_json(self) -> Path:
        return self.assumptions_dir / "briefs.json"

    @property
    def business_csv(self) -> Path:
        return self.assumptions_dir / "business.csv"

    @property
    def regulatory_csv(self) -> Path:
        return self.assumptions_dir / "regulatory.csv"

    @property
    def inci_synonyms_csv(self) -> Path:
        return self.assumptions_dir / "inci_synonyms.csv"

    @property
    def virtual_lab_dir(self) -> Path:
        return self.data_dir / "virtual_lab"

    def historical_csv(self, variant: str = "v1") -> Path:
        return self.virtual_lab_dir / f"historical_{variant}.csv"

    @property
    def variants_json(self) -> Path:
        return self.virtual_lab_dir / "variants.json"

    @property
    def market_data_dir(self) -> Path:
        return self.data_dir / "market"

    @property
    def liposome_dir(self) -> Path:
        return self.data_dir / "validation" / "liposome"

    @property
    def artifacts_dir(self) -> Path:
        return self.fp_home / "artifacts"

    @property
    def base_models_dir(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def evaluation_json(self) -> Path:
        return self.artifacts_dir / "evaluation.json"

    @property
    def figures_dir(self) -> Path:
        return self.artifacts_dir / "figures"

    @property
    def market_artifacts_dir(self) -> Path:
        return self.artifacts_dir / "market"

    @property
    def ingredient_stats_json(self) -> Path:
        return self.market_artifacts_dir / "ingredient_stats.json"

    @property
    def scout_artifacts_dir(self) -> Path:
        return self.artifacts_dir / "scout"

    @property
    def contracts_dir(self) -> Path:
        return self.fp_home / "contracts"

    @property
    def fixtures_dir(self) -> Path:
        return self.contracts_dir / "fixtures"

    @property
    def runtime_models_dir(self) -> Path:
        return self.runtime_dir / "models"

    @property
    def runtime_logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def runtime_run_dir(self) -> Path:
        return self.runtime_dir / "run"

    @property
    def db_path(self) -> Path:
        return self.runtime_dir / "app.db"

    @property
    def log_path(self) -> Path:
        return self.runtime_logs_dir / "app.log"

    @property
    def pid_path(self) -> Path:
        return self.runtime_run_dir / "app.pid"

    @property
    def locks_dir(self) -> Path:
        return self.fp_home / "var" / "locks"

    def test_dir(self, member: Optional[str] = None) -> Path:
        return self.fp_home / "var" / "test" / (member or self.member)

    def ensure_runtime_dirs(self) -> None:
        for d in (self.runtime_models_dir, self.runtime_logs_dir, self.runtime_run_dir):
            d.mkdir(parents=True, exist_ok=True)


def _build() -> Settings:
    home = Path(_env("FP_HOME", str(FP_HOME_DEFAULT))).expanduser().resolve()
    _load_dotenv(home / ".env")

    member = _env("FP_MEMBER", "local")
    instance = _env("INSTANCE", member)
    port = _env_int("APP_PORT", 8000)
    notebook_id = _env("NOTEBOOK_ID", "")
    root_path = os.environ.get("PUBLIC_ROOT_PATH")
    if root_path is None:
        root_path = f"/respati/{notebook_id}/proxy/{port}" if notebook_id else ""
    runtime = _env("FP_RUNTIME_DIR", str(home / "var" / instance))

    return Settings(
        fp_home=home,
        member=member,
        instance=instance,
        app_port=port,
        public_root_path=root_path.rstrip("/"),
        notebook_id=notebook_id,
        runtime_dir=_resolve(home, runtime),
        frontend_dist=_resolve(home, _env("FRONTEND_DIST", "frontend/dist")),
        default_brief=_env("DEFAULT_BRIEF", "niacinamide_gel_cream"),
        default_seed=_env_int("DEFAULT_SEED", 42),
        virtual_lab_variant=_env("VIRTUAL_LAB_VARIANT", "v1"),
        unc_max=_env_float("UNC_MAX", None),
        llm_base_url=_env("LLM_BASE_URL", "http://localhost:8080/v1").rstrip("/"),
        llm_model=_env("LLM_MODEL", "qwen3-30b"),
        llm_api_key=_env("LLM_API_KEY", "none"),
        llm_timeout_s=_env_float("LLM_TIMEOUT_S", 30.0) or 30.0,
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.2) or 0.0,
        orch_max_steps=_env_int("ORCH_MAX_STEPS", 10),
        orch_total_timeout_s=_env_float("ORCH_TOTAL_TIMEOUT_S", 75.0) or 75.0,
        scout_query_device=_env("SCOUT_QUERY_DEVICE", "cpu"),
        scout_build_device=_env("SCOUT_BUILD_DEVICE", "cuda"),
        scheduler_enabled=_env_bool("SCHEDULER_ENABLED", False),
        agent_warmup=_env_bool("AGENT_WARMUP", True),
        designer_n_samples=_env_int("DESIGNER_N_SAMPLES", 0) or None,
        run_timeout_s=_env_float("RUN_TIMEOUT_S", 180.0) or 180.0,
        allowed_origins=tuple(o.strip() for o in _env("ALLOWED_ORIGINS", "").split(",") if o.strip()),
    )


_settings: Optional[Settings] = None


def get_settings(refresh: bool = False) -> Settings:
    global _settings
    if _settings is None or refresh:
        _settings = _build()
    return _settings
