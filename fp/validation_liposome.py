"""Validasi metode pada data eksperimen nyata (liposom, non-skincare) — PRD §8.4, §10.5.

Pemilik: Marshal (A); ditulis ulang Nico saat ambil alih. Data ini TIDAK dipakai melatih model skincare.

    python -m fp.validation_liposome --download     # data/validation/liposome/ (dipanggil fetch_data.sh)
    python -m fp.validation_liposome --summary      # 306 baris, 38 hit
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

URL = "https://zenodo.org/api/records/17867478/files/microfluidics_dataset.zip/content"
ZIP_NAME = "microfluidics_dataset.zip"
CSV_IN_ZIP = "microfluidics_dataset/data/formulations.csv"
CLEAN_NAME = "formulations_clean.csv"
MANIFEST_NAME = "manifest.json"
LICENSE = "CC BY 4.0 (Zenodo 17867478, DOI 10.5281/zenodo.17867478)"  # dicek via API Zenodo 17 Sep; PRD menulis CC BY-NC (keliru)
LABEL = "Validasi metode pada data eksperimen nyata (liposom, non-skincare)"

NUMERIC = ["ESM", "HSPC", "CHOL", "PEG", "TFR", "FRR"]
FEATURES = NUMERIC + ["PBS"]
SIZE_MIN, SIZE_MAX, PDI_MAX = 100.0, 150.0, 0.15
PDI_CLIP = (0.01, 1.0)

PathLike = Union[str, Path]


def data_dir() -> Path:
    from fp.config import get_settings

    return get_settings().liposome_dir


# ---------------------------------------------------------------- data


def download(force: bool = False) -> Path:
    """Unduh zip Zenodo (atomik), simpan CSV bersih + manifest."""
    import requests

    from fp.io_utils import write_bytes

    target = data_dir() / ZIP_NAME
    if target.exists() and target.stat().st_size > 50_000 and not force:
        print(f"liposom: {target} sudah ada, lewati (pakai --force untuk ulang)")
    else:
        resp = requests.get(URL, timeout=(15, 120))
        resp.raise_for_status()
        zipfile.ZipFile(io.BytesIO(resp.content)).getinfo(CSV_IN_ZIP)  # validasi isi sebelum ditulis
        write_bytes(target, resp.content)
        print(f"liposom: unduh {len(resp.content):,} byte -> {target}")
    write_clean()
    return target


def load_raw(zip_path: Optional[PathLike] = None) -> pd.DataFrame:
    z = zipfile.ZipFile(zip_path or data_dir() / ZIP_NAME)
    return pd.read_csv(io.BytesIO(z.read(CSV_IN_ZIP)), encoding="latin-1")


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Baris dengan SIZE & PDI; fitur 6 numerik (FRR kosong -> median) + PBS (0/1)."""
    d = raw.dropna(subset=["SIZE", "PDI"]).copy()
    for c in NUMERIC:
        d[c] = pd.to_numeric(d[c], errors="coerce")
        d[c] = d[c].fillna(d[c].median())
    col = "AQUEOUS" if "AQUEOUS" in d.columns else "AQUEOUS(MQ/PBS)"
    d["PBS"] = d[col].astype(str).str.strip().str.upper().eq("PBS").astype(int) if col in d.columns else 0
    d["HIT"] = is_hit(d["SIZE"].to_numpy(float), d["PDI"].to_numpy(float)).astype(int)
    d = d[FEATURES + ["SIZE", "PDI", "HIT"]].reset_index(drop=True)
    d.insert(0, "row_id", [f"L{i + 1:03d}" for i in range(len(d))])
    return d


def is_hit(size: np.ndarray, pdi: np.ndarray) -> np.ndarray:
    return (size >= SIZE_MIN) & (size <= SIZE_MAX) & (pdi < PDI_MAX)


def write_clean() -> pd.DataFrame:
    from fp.config import now_iso
    from fp.io_utils import write_csv, write_json

    df = clean(load_raw())
    write_csv(data_dir() / CLEAN_NAME, df)
    write_json(
        data_dir() / MANIFEST_NAME,
        {
            "source": URL,
            "license": LICENSE,
            "file": CSV_IN_ZIP,
            "encoding": "latin-1",
            "rows": len(df),
            "hits": int(df["HIT"].sum()),
            "target": {"size_min": SIZE_MIN, "size_max": SIZE_MAX, "pdi_max": PDI_MAX},
            "features": FEATURES,
            "created_at": now_iso(),
        },
    )
    return df


def load_clean() -> pd.DataFrame:
    path = data_dir() / CLEAN_NAME
    if path.exists():
        return pd.read_csv(path)
    if (data_dir() / ZIP_NAME).exists():
        return write_clean()
    raise FileNotFoundError(f"data liposom belum diunduh ({data_dir()}); jalankan fetch_data.sh")


def targets(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return np.log(df["SIZE"].to_numpy(float)), np.log(np.clip(df["PDI"].to_numpy(float), *PDI_CLIP))


# ---------------------------------------------------------------- model 2 output


def _kernel():
    return ConstantKernel(1.0) * Matern(length_scale=np.ones(len(FEATURES)), length_scale_bounds=(1e-2, 1e3), nu=2.5) + WhiteKernel(
        1e-2, (1e-6, 1e0)
    )


class LiposomeModel:
    """GP untuk log(SIZE) dan log(PDI); P_TARGET = P(100 ≤ SIZE ≤ 150) · P(PDI < 0,15)."""

    def __init__(self, seed: int = 42, n_restarts_optimizer: int = 0):
        self.seed = seed
        self.n_restarts_optimizer = n_restarts_optimizer
        self.scaler: Optional[StandardScaler] = None
        self.gp_size: Optional[GaussianProcessRegressor] = None
        self.gp_pdi: Optional[GaussianProcessRegressor] = None

    def fit(self, df: pd.DataFrame) -> "LiposomeModel":
        X = df[FEATURES].to_numpy(float)
        ys, yp = targets(df)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        kw = dict(normalize_y=True, n_restarts_optimizer=self.n_restarts_optimizer, random_state=self.seed)
        self.gp_size = GaussianProcessRegressor(kernel=_kernel(), **kw).fit(Xs, ys)
        self.gp_pdi = GaussianProcessRegressor(kernel=_kernel(), **kw).fit(Xs, yp)
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        Xs = self.scaler.transform(df[FEATURES].to_numpy(float))
        ms, ss = self.gp_size.predict(Xs, return_std=True)
        mp, sp = self.gp_pdi.predict(Xs, return_std=True)
        ss, sp = np.maximum(ss, 1e-9), np.maximum(sp, 1e-9)
        p_size = norm.cdf((np.log(SIZE_MAX) - ms) / ss) - norm.cdf((np.log(SIZE_MIN) - ms) / ss)
        p_pdi = norm.cdf((np.log(PDI_MAX) - mp) / sp)
        return pd.DataFrame(
            {"mu_log_size": ms, "sd_log_size": ss, "mu_log_pdi": mp, "sd_log_pdi": sp, "P_TARGET": np.clip(p_size * p_pdi, 0, 1)}
        )


# ---------------------------------------------------------------- evaluasi (§10.5)


def cross_validate(df: pd.DataFrame, n_splits: int = 5, seed: int = 42) -> dict[str, Optional[float]]:
    ys, yp = targets(df)
    pred_s, pred_p = np.zeros(len(df)), np.zeros(len(df))
    for tr, te in KFold(n_splits, shuffle=True, random_state=seed).split(df):
        p = LiposomeModel(seed=seed).fit(df.iloc[tr]).predict(df.iloc[te])
        pred_s[te], pred_p[te] = p["mu_log_size"], p["mu_log_pdi"]
    return {
        "size_nm_mae": float(np.mean(np.abs(np.exp(ys) - np.exp(pred_s)))),
        "size_nm_median_ae": float(np.median(np.abs(np.exp(ys) - np.exp(pred_s)))),
        "pdi_mae": float(np.mean(np.abs(np.exp(yp) - np.exp(pred_p)))),
        "log_size_r2": _r2(ys, pred_s),
        "log_pdi_r2": _r2(yp, pred_p),
    }


def replay_seed(df: pd.DataFrame, seed: int, strategy: str, max_steps: int = 60, start_known: int = 5) -> Optional[int]:
    """Langkah ke berapa hit pertama ditemukan (None jika tidak dalam max_steps)."""
    rng = np.random.RandomState(seed)
    hits = df["HIT"].to_numpy()
    known = [int(i) for i in rng.choice(np.flatnonzero(hits == 0), size=start_known, replace=False)]
    taken = set(known)
    remaining = [i for i in range(len(df)) if i not in taken]
    for step in range(1, max_steps + 1):
        if not remaining:
            return None
        if strategy == "ai":
            p = LiposomeModel(seed=seed).fit(df.iloc[known]).predict(df.iloc[remaining])["P_TARGET"].to_numpy()
            pick = remaining[int(np.argmax(p))] if p.max() > 0 else remaining[int(rng.randint(len(remaining)))]
        else:
            pick = remaining[int(rng.randint(len(remaining)))]
        known.append(pick)
        remaining.remove(pick)
        if hits[pick]:
            return step
    return None


def _r2(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    denom = float(np.sum((y - y.mean()) ** 2))
    return None if denom == 0 else float(1 - np.sum((y - p) ** 2) / denom)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fp.validation_liposome")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    if not (args.download or args.summary):
        parser.print_help()
        return 2
    if args.download:
        try:
            download(force=args.force)
        except Exception as exc:
            print(f"liposom: unduh gagal: {exc}", file=sys.stderr)
            return 1
    if args.summary:
        t = time.perf_counter()
        df = load_clean()
        print(f"liposom: {len(df)} baris, {int(df['HIT'].sum())} hit; CV {cross_validate(df)} ({time.perf_counter() - t:.1f} dtk)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
