"""Penulisan atomik untuk semua data dan artefak (PRD R19). Pemilik: David (B).

Setiap writer menulis ke file sementara di folder yang sama, lalu `os.replace` ke path tujuan,
sehingga pembaca lain tidak pernah melihat file setengah jadi. File sementara mempertahankan
ekstensi asli (`.x.tmp-<id>.csv.gz`) agar pandas/matplotlib tetap mengenali format dan kompresi.

    from fp.io_utils import write_json, write_csv, write_joblib, read_json
    write_json(settings.evaluation_json, report)
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Union

PathLike = Union[str, os.PathLike]

_MISSING = object()


def _split_name(name: str) -> tuple[str, str]:
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    stem, dot, rest = name.partition(".")
    return stem, (dot + rest) if dot else ""


def _tmp_path(target: Path) -> Path:
    stem, suffix = _split_name(target.name)
    return target.with_name(f".{stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{suffix}")


def _fsync_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def atomic_path(path: PathLike) -> Iterator[Path]:
    """Beri path sementara; saat blok selesai tanpa error, ganti tujuan secara atomik."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(target)
    try:
        yield tmp
        if not tmp.exists():
            raise FileNotFoundError(f"writer tidak membuat file sementara: {tmp}")
        _fsync_file(tmp)
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def write_bytes(path: PathLike, data: bytes) -> Path:
    with atomic_path(path) as tmp:
        tmp.write_bytes(data)
    return Path(path)


def write_text(path: PathLike, text: str, encoding: str = "utf-8") -> Path:
    with atomic_path(path) as tmp:
        with open(tmp, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
    return Path(path)


def to_jsonable(obj: Any) -> Any:
    """Ubah numpy, pandas, pydantic, datetime, Path, set ke tipe JSON. NaN/inf menjadi null."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    mod = type(obj).__module__
    if mod.startswith("numpy"):
        if hasattr(obj, "tolist"):
            return to_jsonable(obj.tolist())
        if hasattr(obj, "item"):
            return to_jsonable(obj.item())
    if mod.startswith("pandas"):
        if hasattr(obj, "to_dict") and hasattr(obj, "columns"):
            return to_jsonable(obj.to_dict(orient="records"))
        if hasattr(obj, "to_dict"):
            return to_jsonable(obj.to_dict())
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
    raise TypeError(f"tidak bisa diubah ke JSON: {type(obj).__name__}")


def dumps_json(obj: Any, indent: int | None = 2) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False, indent=indent, allow_nan=False)


def write_json(path: PathLike, obj: Any, indent: int | None = 2) -> Path:
    return write_text(path, dumps_json(obj, indent=indent) + "\n")


def read_json(path: PathLike, default: Any = _MISSING) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default


def write_csv(path: PathLike, table: Any, index: bool = False, **kwargs: Any) -> Path:
    """`table` = pandas DataFrame, atau list of dict (kolom dari key baris pertama)."""
    with atomic_path(path) as tmp:
        if hasattr(table, "to_csv"):
            table.to_csv(tmp, index=index, **kwargs)
        else:
            import csv

            rows = list(table)
            fields = list(rows[0].keys()) if rows else []
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
    return Path(path)


def write_parquet(path: PathLike, df: Any, index: bool = False, **kwargs: Any) -> Path:
    with atomic_path(path) as tmp:
        df.to_parquet(tmp, index=index, **kwargs)
    return Path(path)


def write_joblib(path: PathLike, obj: Any, compress: int = 0) -> Path:
    import joblib

    with atomic_path(path) as tmp:
        joblib.dump(obj, tmp, compress=compress)
    return Path(path)


def load_joblib(path: PathLike) -> Any:
    import joblib

    return joblib.load(path)


def write_npy(path: PathLike, array: Any) -> Path:
    import numpy as np

    with atomic_path(path) as tmp:
        with open(tmp, "wb") as f:
            np.save(f, array)
    return Path(path)


def write_figure(path: PathLike, fig: Any, **savefig_kwargs: Any) -> Path:
    """Simpan figure matplotlib; format dari ekstensi path tujuan."""
    target = Path(path)
    savefig_kwargs.setdefault("format", target.suffix.lstrip(".") or "png")
    with atomic_path(target) as tmp:
        fig.savefig(tmp, **savefig_kwargs)
    return target


def write_with(path: PathLike, writer: Callable[[Path], Any]) -> Path:
    """Untuk format lain: `writer(tmp_path)` menulis file, lalu diganti atomik."""
    with atomic_path(path) as tmp:
        writer(tmp)
    return Path(path)
