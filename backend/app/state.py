"""State aplikasi per instance: DB, data asumsi, model aktif, cache, lock (PRD §14.1). Pemilik: David (B).

Modul milik anggota lain (`fp.palette`, `fp.designer`, `fp.registry`, `fp.guardian`, `fp.market`, `fp.scout`)
di-import secara defensif: jika belum ada atau error, app tetap hidup dan `/health` melaporkannya (R23).
"""

from __future__ import annotations

import csv
import importlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

from fp import schemas as S
from fp.config import Settings, get_settings
from fp.orchestrator.client import LlmHealth

from . import repo
from .db import Database

log = logging.getLogger("formulapilot.state")

BASE_MODEL_VERSION = "gp-global-v1"

PROCESS_META = {
    "RPM": ("Kecepatan homogenizer", "rpm", 2000.0, 10000.0),
    "HMIN": ("Lama homogenisasi", "menit", 1.0, 10.0),
    "TEMP": ("Suhu emulsifikasi", "°C", 60.0, 85.0),
}


def optional_module(name: str) -> tuple[Optional[ModuleType], Optional[str]]:
    try:
        return importlib.import_module(name), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


class FileCache:
    """Muat ulang file hanya jika mtime berubah, sehingga data A-00 yang datang belakangan langsung terbaca."""

    def __init__(self, path: Path, loader: Callable[[Path], Any]) -> None:
        self.path = path
        self.loader = loader
        self._mtime: Optional[float] = None
        self._value: Any = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def get(self) -> Any:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self.error = f"{self.path.name} belum ada"
            self._mtime, self._value = None, None
            return None
        if mtime != self._mtime:
            with self._lock:
                if mtime != self._mtime:
                    try:
                        self._value = self.loader(self.path)
                        self.error = None
                    except Exception as exc:
                        log.warning("gagal memuat %s: %s", self.path, exc)
                        self._value = None
                        self.error = f"{self.path.name} tidak valid: {exc}"
                    self._mtime = mtime
        return self._value


def _load_briefs(path: Path) -> dict[str, S.Brief]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    briefs = [S.Brief.model_validate(item) for item in raw]
    return {b.brief_id: b for b in briefs}


def _float_or(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _load_palette(path: Path) -> S.Palette:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ingredients = [
        S.PaletteIngredient(
            code=r["code"].strip(),
            inci=r["inci"].strip(),
            role=r["role"].strip(),
            min_pct=_float_or(r.get("min_pct"), 0.0),
            max_pct=_float_or(r.get("max_pct"), 0.0),
            price_idr_per_kg=_float_or(r.get("price_idr_per_kg"), 0.0),
            notes=(r.get("notes") or "").strip() or None,
        )
        for r in rows
        if r.get("code")
    ]
    process = [S.ProcessParam(code=c, label=lbl, unit=u, min=lo, max=hi) for c, (lbl, u, lo, hi) in PROCESS_META.items()]
    return S.Palette(ingredients=ingredients, process=process)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class AppState:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(self.settings.db_path)
        self.llm = LlmHealth(self.settings.llm_base_url)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fp-run")
        self.briefs = FileCache(self.settings.briefs_json, _load_briefs)
        self.palette = FileCache(self.settings.ingredients_csv, _load_palette)
        self.evaluation = FileCache(self.settings.evaluation_json, _load_json)
        self.figures_dir = self.settings.figures_dir
        self.historical_path = self.settings.historical_csv("v1")
        self.db_ready = False
        self.model_error: Optional[str] = None
        self._designers: dict[str, tuple[str, Any]] = {}
        self._designer_lock = threading.Lock()
        self._model_locks: dict[str, threading.Lock] = {}
        self._model_locks_guard = threading.Lock()
        self.scheduler: Any = None

    # lifecycle

    def startup(self) -> None:
        self.settings.ensure_runtime_dirs()
        self.db.init()
        self.db_ready = self.db.ping()
        stale = repo.fail_stale_runs(self.db, "Server dinyalakan ulang saat run berjalan.")
        if stale:
            log.warning("%d run berstatus running ditandai failed saat startup", stale)
        self.load_global_designer()
        if self.settings.scheduler_enabled:
            try:
                from .scheduler import AgentScheduler

                self.scheduler = AgentScheduler(self)
                self.scheduler.start()
            except Exception as exc:
                log.warning("scheduler gagal dinyalakan: %s", exc)
                self.scheduler = None
        if self.settings.agent_warmup:
            threading.Thread(target=self.warmup_agents, name="fp-warmup", daemon=True).start()
        log.info(
            "startup instance=%s db=%s model_ready=%s briefs=%s palette=%s",
            self.settings.instance,
            self.settings.db_path,
            self.model_ready,
            self.briefs.get() is not None,
            self.palette.get() is not None,
        )

    def warmup_agents(self) -> None:
        """§14.1 langkah 6: muat market dan model query Scout di latar; kegagalan tidak menghentikan app."""
        for name in ("fp.market", "fp.scout"):
            module, err = optional_module(name)
            if module is None:
                log.info("warmup %s dilewati: %s", name, err)
                continue
            try:
                fn = getattr(module, "warmup", None) or getattr(module, "status", None)
                result = fn() if fn else None
                log.info("warmup %s selesai: %s", name, result if isinstance(result, (bool, dict)) else "ok")
            except Exception as exc:
                log.warning("warmup %s gagal: %s", name, exc)

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown()
        self.executor.shutdown(wait=False, cancel_futures=True)

    # model

    def model_lock(self, scope: str) -> threading.Lock:
        with self._model_locks_guard:
            return self._model_locks.setdefault(scope, threading.Lock())

    def load_designer_file(self, path: Path) -> Any:
        mod, err = optional_module("fp.designer")
        if mod is None:
            raise RuntimeError(f"fp.designer belum bisa di-import ({err})")
        cls = mod.Designer
        try:
            obj = cls.load(path)
            if isinstance(obj, cls):
                return obj
        except TypeError:
            pass
        inst = cls()
        res = inst.load(path)
        return res if isinstance(res, cls) else inst

    def load_global_designer(self) -> None:
        row = repo.active_model_version(self.db, "global")
        path = Path(row["path"]) if row else self.settings.base_models_dir / f"{BASE_MODEL_VERSION}.joblib"
        if not path.exists():
            self.model_error = f"model {path.name} belum ada (menunggu A-06)"
            return
        try:
            designer = self.load_designer_file(path)
        except Exception as exc:
            self.model_error = f"gagal memuat {path.name}: {exc}"
            log.warning(self.model_error)
            return
        version = row["version"] if row else getattr(designer, "version", None) or BASE_MODEL_VERSION
        if row is None:
            repo.add_model_version(
                self.db, version, "global", str(path), int(getattr(designer, "n_train", 0) or 0), None, activate=True
            )
        self.set_designer("global", version, designer)
        self.model_error = None

    def set_designer(self, scope: str, version: str, designer: Any) -> None:
        with self._designer_lock:
            self._designers[scope] = (version, designer)

    def clear_designer(self, scope: str) -> None:
        with self._designer_lock:
            self._designers.pop(scope, None)

    def get_designer(self, scope: str = "global") -> Optional[tuple[str, Any]]:
        with self._designer_lock:
            return self._designers.get(scope)

    @property
    def model_ready(self) -> bool:
        return self.get_designer("global") is not None

    @property
    def model_version(self) -> Optional[str]:
        entry = self.get_designer("global")
        return entry[0] if entry else None

    # status

    def unc_max(self) -> Optional[float]:
        report = self.evaluation.get()
        if isinstance(report, dict) and report.get("unc_max") is not None:
            return float(report["unc_max"])
        return self.settings.unc_max

    def optional_status(self, module_name: str) -> dict[str, Any]:
        mod, err = optional_module(module_name)
        if mod is None or not hasattr(mod, "status"):
            return {"ready": False, "reason": err or "status() belum ada"}
        try:
            status = mod.status()
            return status if isinstance(status, dict) else dict(status)
        except Exception as exc:
            return {"ready": False, "reason": f"{type(exc).__name__}: {exc}"}

    def mode(self) -> str:
        return "live" if self.model_ready and self.llm.ready() else "degraded"

    def health(self) -> S.Health:
        return S.Health(
            model_ready=self.model_ready,
            model_version=self.model_version,
            llm_ready=self.llm.ready(),
            scout_ready=bool(self.optional_status("fp.scout").get("ready")),
            market_ready=bool(self.optional_status("fp.market").get("ready")),
            evaluation_ready=isinstance(self.evaluation.get(), dict),
            db_ready=self.db.ping(),
            instance=self.settings.instance,
            virtual_lab_variant=self.settings.virtual_lab_variant,
        )
