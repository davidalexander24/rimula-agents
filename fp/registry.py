"""Registry versi model Designer (PRD §9.6). Pemilik: Marshal (A); ditulis ulang Nico saat ambil alih.

- Model dasar (offline, train.sh): `artifacts/models/<version>.joblib` + `.json` (base_dir).
- Model hasil retrain (runtime): `$FP_RUNTIME_DIR/models/<version>.joblib` + `.json` (model_dir).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from fp.designer import Designer

PathLike = Union[str, Path]


def _dirs(model_dir: Optional[PathLike], base_dir: Optional[PathLike]) -> tuple[Path, Path]:
    from fp.config import get_settings

    s = get_settings()
    return Path(model_dir or s.runtime_models_dir), Path(base_dir or s.base_models_dir)


def register(designer: Designer, model_dir: Optional[PathLike] = None, base_dir: Optional[PathLike] = None) -> Path:
    """Simpan designer ke model_dir/<version>.joblib (+ .json, atomik)."""
    mdir, _ = _dirs(model_dir, base_dir)
    return designer.save(mdir / f"{designer.version}.joblib")


def list_versions(
    scope: Optional[str] = None, model_dir: Optional[PathLike] = None, base_dir: Optional[PathLike] = None
) -> list[dict[str, Any]]:
    """Metadata semua versi (runtime dulu, lalu dasar), terbaru dulu. Tiap item memuat `path` dan `location`."""
    from fp.io_utils import read_json

    mdir, bdir = _dirs(model_dir, base_dir)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for location, folder in (("runtime", mdir), ("base", bdir)):
        if not folder.is_dir():
            continue
        for meta_path in folder.glob("*.json"):
            model_path = meta_path.with_suffix(".joblib")
            if not model_path.exists():
                continue
            meta = read_json(meta_path, default={}) or {}
            version = meta.get("version") or meta_path.stem
            if version in seen or (scope and meta.get("scope", "global") != scope):
                continue
            seen.add(version)
            items.append({**meta, "version": version, "path": str(model_path), "location": location})
    items.sort(key=lambda m: (m["location"] == "runtime", str(m.get("created_at") or "")), reverse=True)
    return items


def latest(scope: str = "global", model_dir: Optional[PathLike] = None, base_dir: Optional[PathLike] = None) -> Optional[dict[str, Any]]:
    """Metadata versi terbaru untuk scope (runtime diutamakan); None bila belum ada."""
    items = list_versions(scope, model_dir, base_dir)
    return items[0] if items else None


def load(version: str, model_dir: Optional[PathLike] = None, base_dir: Optional[PathLike] = None) -> Designer:
    """Muat versi dari model_dir, lalu base_dir."""
    mdir, bdir = _dirs(model_dir, base_dir)
    for folder in (mdir, bdir):
        path = folder / f"{version}.joblib"
        if path.exists():
            return Designer.load(path)
    raise FileNotFoundError(f"model {version} tidak ada di {mdir} maupun {bdir}")
