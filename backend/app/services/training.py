"""Data training dan retrain Designer per scope (PRD §9.6, §14.4, R20). Pemilik: David (B).

Scope `global` = `historical_v1.csv` + hasil lab aktif scope global. Model hasil retrain disimpan di
`$FP_RUNTIME_DIR/models/` dan tidak pernah menulis ke `artifacts/`.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from fp import schemas as S
from fp.io_utils import write_joblib

from .. import repo
from ..state import AppState, optional_module

log = logging.getLogger("formulapilot.training")

TARGET_COLUMNS = ("VISCOSITY_CP", "PH", "D50_UM", "STABILITY_INDEX")
PREV_PARAM_NAMES = ("prev", "previous", "prev_designer", "warm_start", "parent", "prior")
VERSION_RE = re.compile(r"-v(\d+)$")
LIVE_RESTARTS = 0


class TrainingError(Exception):
    pass


def version_prefix(scope: str) -> str:
    return "gp-global" if scope == "global" else f"gp-session-{scope.split(':', 1)[1]}"


def next_version(state: AppState, scope: str) -> str:
    highest = 1
    for mv in repo.list_model_versions(state.db, scope):
        m = VERSION_RE.search(mv.version)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{version_prefix(scope)}-v{highest + 1}"


def lab_frame(state: AppState, scope: str):
    import pandas as pd

    rows = []
    for r in repo.active_lab_rows(state.db, scope):
        formula = json.loads(r["formula_json"])
        outputs = json.loads(r["outputs_json"])
        rows.append({**{k: formula[k] for k in S.FORMULA_FIELDS}, **{k: outputs.get(k) for k in TARGET_COLUMNS}})
    return pd.DataFrame(rows, columns=list(S.FORMULA_FIELDS) + list(TARGET_COLUMNS))


def global_training_table(state: AppState):
    import pandas as pd

    path = Path(state.historical_path)
    if not path.is_file():
        raise TrainingError(f"{path.name} belum ada (menunggu A-04)")
    hist = pd.read_csv(path)
    missing = [c for c in list(S.FORMULA_FIELDS) + list(TARGET_COLUMNS) if c not in hist.columns]
    if missing:
        raise TrainingError(f"kolom {missing} tidak ada di {path.name}")
    hist = hist[list(S.FORMULA_FIELDS) + list(TARGET_COLUMNS)]
    labs = lab_frame(state, "global")
    table = pd.concat([hist, labs], ignore_index=True) if len(labs) else hist
    return table.dropna(subset=list(TARGET_COLUMNS)).reset_index(drop=True)


_scaled_cache: dict[str, Any] = {}


def scaled_training_features(state: AppState, version: str, designer: Any) -> Optional[Any]:
    """Data training ter-scale untuk cek EXTRAPOLATION Guardian. Pakai `designer.train_X_scaled` bila ada;
    jika tidak, hitung sekali per versi dari data training scope global dengan scaler dan fitur milik Designer."""
    own = getattr(designer, "train_X_scaled", None)
    if own is not None:
        return own
    if version in _scaled_cache:
        return _scaled_cache[version]
    scaler, frame = getattr(designer, "scaler", None), getattr(designer, "_frame", None)
    if scaler is None or not callable(frame) or not version.startswith("gp-global"):
        return None
    try:
        table = global_training_table(state)
        value = scaler.transform(frame(table[list(S.FORMULA_FIELDS)]))
    except Exception as exc:
        log.warning("train_X_scaled untuk %s tidak bisa dihitung: %s", version, exc)
        value = None
    _scaled_cache[version] = value
    return value


def _fit(prev: Any, table, template: Any = None) -> Any:
    fresh = type(template if template is not None else prev)()
    fit = fresh.fit
    signature = inspect.signature(fit).parameters
    params = [p for p in signature.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    required = [p for p in params if p.default is p.empty]
    kwargs: dict[str, Any] = {}
    for name in PREV_PARAM_NAMES:
        if name in signature and prev is not None:
            kwargs[name] = prev
            break
    if "n_restarts_optimizer" in signature:
        kwargs["n_restarts_optimizer"] = LIVE_RESTARTS
    if len(required) >= 2:
        result = fit(table[list(S.FORMULA_FIELDS)], table[list(TARGET_COLUMNS)], **kwargs)
    else:
        result = fit(table, **kwargs)
    return result if result is not None else fresh


def _save(designer: Any, path: Path) -> None:
    save = getattr(designer, "save", None)
    if callable(save):
        save(path)
    else:
        write_joblib(path, designer)


def _register(state: AppState, scope: str, version: str, designer: Any, table, parent: Optional[str]) -> int:
    for attr, value in (("version", version), ("scope", scope)):
        try:
            setattr(designer, attr, value)
        except AttributeError:
            pass
    n_train = int(getattr(designer, "n_train", 0) or len(table))
    path = state.settings.runtime_models_dir / f"{version}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(designer, path)
    repo.add_model_version(state.db, version, scope, str(path), n_train, parent, activate=True)
    state.set_designer(scope, version, designer)
    return n_train


def fit_new(state: AppState, scope: str, table, template: Any) -> tuple[str, Any, int]:
    """Model pertama sebuah scope (sesi replay): dilatih dari nol dengan kelas Designer yang sama dengan `template`."""
    with state.model_lock(scope):
        designer = _fit(None, table, template=template)
        version = f"{version_prefix(scope)}-v1"
        n_train = _register(state, scope, version, designer, table, None)
    return version, designer, n_train


def retrain(state: AppState, scope: str, table=None) -> tuple[str, Any, int]:
    """Latih ulang Designer scope dengan warm start dari model aktif, simpan, daftarkan, aktifkan."""
    started = time.perf_counter()
    with state.model_lock(scope):
        entry = state.get_designer(scope)
        if entry is None:
            raise TrainingError(f"model aktif untuk scope {scope} belum ada")
        prev_version, prev = entry
        if table is None:
            if scope != "global":
                raise TrainingError("data training sesi harus diberikan pemanggil")
            table = global_training_table(state)
        designer = _fit(prev, table)
        version = next_version(state, scope)
        n_train = _register(state, scope, version, designer, table, prev_version)
    log.info("retrain %s → %s n_train=%d %.1fs", scope, version, n_train, time.perf_counter() - started)
    return version, designer, n_train


def reset_global(state: AppState, base_version: str) -> Optional[str]:
    """Arsipkan hasil lab global dan kembalikan model aktif ke model dasar."""
    with state.model_lock("global"):
        repo.archive_scope(state.db, "global")
        if not repo.activate_model_version(state.db, base_version):
            repo.deactivate_scope(state.db, "global")
        state.clear_designer("global")
        state.load_global_designer()
    return state.model_version
