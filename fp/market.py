"""Scout pasar: statistik Open Beauty Facts (PRD §8.3, §12.2). Pemilik: Nico (D).

    python -m fp.market --download     # data/market/obf_raw.csv.gz (D-05)
    python -m fp.market --build        # parquet bersih + artifacts/market/ingredient_stats.json (D-06)

    from fp import market
    market.status()                                  # {"ready": True, "n_products": ..., "built_at": ...}
    market.support(["NIACINAMIDE", "GLYCERIN"])      # dict type="market" (≤ 200 ms)
    market.evidence(market.support(codes))           # fp.schemas.Evidence atau None
    market.stats()                                   # isi ingredient_stats.json -> GuardianContext.market

Jika artefak belum dibangun: `status()["ready"]` = False dan `support()` kosong + `reason`.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

import numpy as np
import pandas as pd

from fp.schemas import INGREDIENT_FIELDS, Evidence

SOURCE = "Open Beauty Facts"
LICENSE = "ODbL"
OBF_URL = "https://static.openbeautyfacts.org/data/en.openbeautyfacts.org.products.csv.gz"
RAW_NAME = "obf_raw.csv.gz"
CLEAN_NAME = "obf_skincare_clean.parquet"
STATS_NAME = "ingredient_stats.json"
RAW_MIN_BYTES = 10_000_000  # dicek 17 Sep: ±17,9 MB

REASON_NOT_READY = "market_not_ready"
REASON_NO_CODES = "no_codes"
SEGMENTS = ("skincare", "makeup", "suncare")
MIN_PCT = 0.1
MAX_EXAMPLES = 3
MIN_INGREDIENTS_LEN = 20

KEY_COLUMNS = [
    "code",
    "product_name",
    "brands",
    "categories_tags",
    "countries_tags",
    "ingredients_text",
    "ingredients_tags",
    "main_category",
]
INCLUDE_CATEGORIES = frozenset(
    {
        "en:face",
        "en:facial-creams",
        "en:body-creams",
        "en:hand-creams",
        "en:makeup",
        "en:suncare",
        "en:sunscreen",
        "en:moisturizers",
        "en:serums",
        "en:lip-balms",
        "en:cosmetic-products",
    }
)
EXCLUDE_CATEGORIES = frozenset({"en:shampoos", "en:toothpastes", "en:deodorants", "en:soaps"})
SUNCARE_CATEGORIES = frozenset({"en:suncare", "en:sunscreen"})
MAKEUP_CATEGORIES = frozenset({"en:makeup"})
INDONESIA_TAG = "en:indonesia"

PathLike = Union[str, Path]


# ---------------------------------------------------------------- path


def _settings():
    from fp.config import get_settings

    return get_settings()


def raw_path() -> Path:
    return _settings().market_data_dir / RAW_NAME


def clean_path() -> Path:
    return _settings().market_data_dir / CLEAN_NAME


def stats_path() -> Path:
    return _settings().ingredient_stats_json


def synonyms_path() -> Path:
    return _settings().inci_synonyms_csv


# ---------------------------------------------------------------- unduh (D-05)


def download(force: bool = False, url: str = OBF_URL, retries: int = 3) -> Path:
    """Unduh dump CSV Open Beauty Facts ke data/market/obf_raw.csv.gz secara atomik (R19)."""
    import gzip

    import requests

    from fp.io_utils import atomic_path

    target = raw_path()
    if target.exists() and target.stat().st_size >= RAW_MIN_BYTES and not force:
        print(f"market: {target} sudah ada ({target.stat().st_size:,} byte), lewati (pakai --force untuk ulang)")
        return target

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            started = time.time()
            with requests.get(url, stream=True, timeout=(15, 120)) as resp:
                resp.raise_for_status()
                with atomic_path(target) as tmp:
                    size = 0
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            fh.write(chunk)
                            size += len(chunk)
                    if size < RAW_MIN_BYTES:
                        raise ValueError(f"ukuran unduhan terlalu kecil: {size:,} byte")
                    with gzip.open(tmp, "rt", encoding="utf-8", errors="replace") as gz:
                        header = gz.readline()
                    if "ingredients_text" not in header.split("\t"):
                        raise ValueError("header TSV tidak memuat kolom ingredients_text")
            print(f"market: unduh {size:,} byte dalam {time.time() - started:.1f} dtk -> {target}")
            return target
        except Exception as exc:  # jaringan/isi rusak -> coba lagi
            last_error = exc
            print(f"market: percobaan {attempt}/{retries} gagal: {exc}", file=sys.stderr)
            time.sleep(min(5 * attempt, 15))
    raise RuntimeError(f"unduh Open Beauty Facts gagal: {last_error}")


# ---------------------------------------------------------------- pembersihan & pemetaan (D-06)


def load_synonyms(path: Optional[PathLike] = None) -> dict[str, list[str]]:
    """inci_synonyms.csv -> {kode palet: [sinonim huruf kecil]}."""
    df = pd.read_csv(path or synonyms_path(), dtype=str, keep_default_na=False)
    out: dict[str, list[str]] = {}
    for row in df.itertuples(index=False):
        code, syn = row.code.strip().upper(), row.synonym.strip().lower()
        if code and syn:
            out.setdefault(code, []).append(syn)
    return out


def compile_patterns(synonyms: Mapping[str, Iterable[str]]) -> dict[str, re.Pattern]:
    """Satu regex per kode; sinonim harus berdiri sebagai kata utuh ("glycerin" tidak cocok "polyglycerin")."""
    patterns = {}
    for code, syns in synonyms.items():
        alts = sorted({_squash(s) for s in syns}, key=len, reverse=True)
        body = "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in alts)
        patterns[code] = re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")
    return patterns


def normalize_ingredients(text: Any, tags: Any) -> str:
    """Huruf kecil; gabungkan ingredients_text dan ingredients_tags (tag "en:cetearyl-alcohol" -> "cetearyl alcohol")."""
    t = _squash(str(text or "").lower())
    g = str(tags or "").lower()
    g = re.sub(r"(^|,)\s*[a-z]{2}:", r"\1", g).replace("-", " ").replace("_", " ").replace(",", " , ")
    return f"{t} | {_squash(g)}"


def map_codes(normalized: str, patterns: Mapping[str, re.Pattern]) -> list[str]:
    return sorted(code for code, pat in patterns.items() if pat.search(normalized))


def segment_of(categories_tags: Any) -> Optional[str]:
    """`skincare`/`makeup`/`suncare`; None bila bukan kategori kosmetik yang dipakai (§8.3 langkah 2)."""
    tags = {t.strip() for t in str(categories_tags or "").lower().split(",") if t.strip()}
    if not tags & INCLUDE_CATEGORIES or tags & EXCLUDE_CATEGORIES:
        return None
    if tags & SUNCARE_CATEGORIES:
        return "suncare"
    if tags & MAKEUP_CATEGORIES:
        return "makeup"
    return "skincare"


def read_raw(path: Optional[PathLike] = None) -> pd.DataFrame:
    return pd.read_csv(
        path or raw_path(),
        sep="\t",
        compression="gzip",
        usecols=lambda c: c in KEY_COLUMNS,
        dtype=str,
        on_bad_lines="skip",
    )


def clean(raw: pd.DataFrame, patterns: Mapping[str, re.Pattern]) -> pd.DataFrame:
    """Langkah 2–6 §8.3 -> kolom `code, product_name, brands, segment, is_indonesia, codes`."""
    df = raw.reindex(columns=KEY_COLUMNS).fillna("")
    df["segment"] = df["categories_tags"].map(segment_of)
    df = df[df["segment"].notna() & (df["ingredients_text"].str.strip().str.len() >= MIN_INGREDIENTS_LEN)]
    has_code = df["code"].str.strip() != ""
    df = pd.concat([df[has_code].drop_duplicates("code"), df[~has_code]])
    normalized = [normalize_ingredients(t, g) for t, g in zip(df["ingredients_text"], df["ingredients_tags"])]
    out = pd.DataFrame(
        {
            "code": df["code"].str.strip().values,
            "product_name": df["product_name"].str.strip().values,
            "brands": df["brands"].str.strip().values,
            "segment": df["segment"].values,
            "is_indonesia": df["countries_tags"].str.lower().str.contains(INDONESIA_TAG, regex=False).values,
            "codes": [map_codes(n, patterns) for n in normalized],
        }
    )
    return out.reset_index(drop=True)


def compute_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Isi ingredient_stats.json (§8.3)."""
    from fp.config import now_iso

    n = len(df)
    masks = _code_masks(df)
    pair_support: dict[str, int] = {}
    examples: dict[str, list[dict[str, str]]] = {}
    for a, b in combinations(sorted(INGREDIENT_FIELDS), 2):
        both = masks[a] & masks[b]
        key = f"{a}|{b}"
        pair_support[key] = int(both.sum())
        if pair_support[key]:
            examples[key] = _examples(df, both, with_segment=False)
    return {
        "built_at": now_iso(),
        "source": SOURCE,
        "license": LICENSE,
        "n_products": n,
        "n_by_segment": {s: int((df["segment"] == s).sum()) for s in SEGMENTS},
        "n_indonesia": int(df["is_indonesia"].sum()),
        "prevalence": {c: (round(float(masks[c].mean()), 6) if n else 0.0) for c in INGREDIENT_FIELDS},
        "pair_support": pair_support,
        "examples": examples,
    }


def build(
    raw: Optional[PathLike] = None,
    out_parquet: Optional[PathLike] = None,
    out_stats: Optional[PathLike] = None,
    synonyms: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Bangun parquet bersih dan ingredient_stats.json (atomik, R19). Mengembalikan stats."""
    from fp.io_utils import write_json, write_parquet

    patterns = compile_patterns(load_synonyms(synonyms))
    df = clean(read_raw(raw), patterns)
    stats_obj = compute_stats(df)
    write_parquet(out_parquet or clean_path(), df)
    write_json(out_stats or stats_path(), stats_obj)
    reload()
    return stats_obj


# ---------------------------------------------------------------- query (dimuat sekali)


class MarketIndex:
    """Bitset per kode bahan untuk `support()` cepat (operasi AND + popcount)."""

    def __init__(self, df: pd.DataFrame, stats_obj: Mapping[str, Any]):
        self.stats = dict(stats_obj)
        self.n = len(df)
        self.product_name = df["product_name"].fillna("").astype(str).tolist()
        self.brands = df["brands"].fillna("").astype(str).tolist()
        self.segment = df["segment"].astype(str).tolist()
        self.all_bits = (1 << self.n) - 1
        self.code_bits = {c: _to_bits(m) for c, m in _code_masks(df).items()}
        self.segment_bits = {s: _to_bits((df["segment"] == s).to_numpy()) for s in SEGMENTS}
        self.indonesia_bits = _to_bits(df["is_indonesia"].to_numpy(dtype=bool))

    @classmethod
    def load(cls, parquet: PathLike, stats_file: PathLike) -> "MarketIndex":
        from fp.io_utils import read_json

        return cls(pd.read_parquet(parquet), read_json(stats_file))

    def support(self, codes: Iterable[str]) -> dict[str, Any]:
        codes = _norm_codes(codes)
        if not codes:
            return _empty_support(codes, REASON_NO_CODES)
        acc = self.all_bits
        for c in codes:
            acc &= self.code_bits.get(c, 0)
        weakest_pair, min_pair = None, None
        for a, b in combinations(codes, 2):
            n_pair = (self.code_bits.get(a, 0) & self.code_bits.get(b, 0)).bit_count()
            if min_pair is None or n_pair < min_pair:
                weakest_pair, min_pair = f"{a}|{b}", n_pair
        return {
            "type": "market",
            "codes": codes,
            "n_products_all": acc.bit_count(),
            "n_by_segment": {s: (acc & bits).bit_count() for s, bits in self.segment_bits.items()},
            "n_indonesia": (acc & self.indonesia_bits).bit_count(),
            "min_pair_support": min_pair,
            "weakest_pair": weakest_pair,
            "examples": self._examples(acc),
            "reason": None,
        }

    def _examples(self, acc: int) -> list[dict[str, str]]:
        """Maks 3 contoh bernama; produk Indonesia didahulukan."""
        out: list[dict[str, str]] = []
        seen: set[int] = set()
        for bits in (acc & self.indonesia_bits, acc):
            while bits and len(out) < MAX_EXAMPLES:
                low = bits & -bits
                i = low.bit_length() - 1
                bits ^= low
                if i in seen or not self.product_name[i]:
                    continue
                seen.add(i)
                out.append({"product_name": self.product_name[i], "brands": self.brands[i], "segment": self.segment[i]})
        return out


_lock = threading.Lock()
_index: Optional[MarketIndex] = None
_index_key: Optional[tuple[float, float]] = None


def _get_index() -> Optional[MarketIndex]:
    global _index, _index_key
    p, s = clean_path(), stats_path()
    try:
        key = (p.stat().st_mtime, s.stat().st_mtime)
    except FileNotFoundError:
        return None
    with _lock:
        if _index is None or _index_key != key:
            try:
                _index, _index_key = MarketIndex.load(p, s), key
            except Exception as exc:  # artefak rusak -> anggap belum siap
                print(f"market: gagal memuat artefak: {exc}", file=sys.stderr)
                _index, _index_key = None, None
        return _index


def reload() -> None:
    """Lupakan cache; dipanggil setelah build."""
    global _index, _index_key
    with _lock:
        _index, _index_key = None, None


def status() -> dict[str, Any]:
    """`ready`, `n_products`, `built_at` (+ `reason` bila belum siap)."""
    idx = _get_index()
    if idx is None:
        return {"ready": False, "n_products": 0, "built_at": None, "reason": REASON_NOT_READY}
    return {"ready": True, "n_products": idx.n, "built_at": idx.stats.get("built_at")}


def stats() -> Optional[dict[str, Any]]:
    """Isi ingredient_stats.json untuk GuardianContext.market; None bila belum siap."""
    idx = _get_index()
    return None if idx is None else idx.stats


def summary() -> Optional[dict[str, Any]]:
    """Ringkasan untuk `GET /market/summary`: stats tanpa `examples`."""
    s = stats()
    return None if s is None else {k: v for k, v in s.items() if k != "examples"}


def codes_for(formula: Any) -> list[str]:
    """Kode bahan kandidat dengan pct ≥ 0,1 (tanpa AQUA), terurut."""
    f = formula.model_dump() if hasattr(formula, "model_dump") else dict(formula)
    return sorted(k for k in INGREDIENT_FIELDS if float(f.get(k, 0.0) or 0.0) >= MIN_PCT)


def support(codes: Iterable[str]) -> dict[str, Any]:
    """Jumlah produk nyata yang memuat semua kode (§12.2)."""
    idx = _get_index()
    if idx is None:
        return _empty_support(_norm_codes(codes), REASON_NOT_READY)
    return idx.support(codes)


def prevalence() -> dict[str, float]:
    """Proporsi produk yang memuat tiap kode palet."""
    s = stats()
    return {} if s is None else dict(s.get("prevalence", {}))


def evidence(result: Mapping[str, Any]) -> Optional[Evidence]:
    """Ubah hasil `support()` menjadi Evidence untuk kandidat; None bila market belum siap."""
    if result.get("reason") or not result.get("codes"):
        return None
    n_all = int(result.get("n_products_all", 0))
    n_id = int(result.get("n_indonesia", 0))
    if n_all > 0:
        title = (
            f"Kombinasi bahan ini ditemukan pada {n_all} produk skincare/makeup (Open Beauty Facts), "
            f"termasuk {n_id} produk di Indonesia."
        )
    else:
        title = "Kombinasi bahan ini belum ditemukan pada produk skincare/makeup di Open Beauty Facts."
    keys = ("codes", "n_products_all", "n_indonesia", "n_by_segment", "min_pair_support", "weakest_pair", "examples")
    return Evidence(type="market", title=title, detail={k: result.get(k) for k in keys}, source=SOURCE)


# ---------------------------------------------------------------- helper


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _norm_codes(codes: Iterable[str]) -> list[str]:
    return sorted({str(c).strip().upper() for c in codes if str(c).strip() and str(c).strip().upper() != "AQUA"})


def _code_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    sets = [set(c) for c in df["codes"]]
    return {code: np.fromiter((code in s for s in sets), dtype=bool, count=len(sets)) for code in INGREDIENT_FIELDS}


def _to_bits(mask: np.ndarray) -> int:
    return int.from_bytes(np.packbits(np.asarray(mask, dtype=bool), bitorder="little").tobytes(), "little")


def _examples(df: pd.DataFrame, mask: np.ndarray, with_segment: bool) -> list[dict[str, str]]:
    sub = df[mask & (df["product_name"].fillna("") != "").to_numpy()]
    sub = pd.concat([sub[sub["is_indonesia"]], sub[~sub["is_indonesia"]]]).head(MAX_EXAMPLES)
    cols = ["product_name", "brands"] + (["segment"] if with_segment else [])
    return [{k: str(v) for k, v in row.items()} for row in sub[cols].to_dict(orient="records")]


def _empty_support(codes: list[str], reason: str) -> dict[str, Any]:
    return {
        "type": "market",
        "codes": codes,
        "n_products_all": 0,
        "n_by_segment": {s: 0 for s in SEGMENTS},
        "n_indonesia": 0,
        "min_pair_support": None,
        "weakest_pair": None,
        "examples": [],
        "reason": reason,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fp.market", description="Statistik Open Beauty Facts")
    parser.add_argument("--download", action="store_true", help="unduh data/market/obf_raw.csv.gz (D-05)")
    parser.add_argument("--force", action="store_true", help="unduh ulang walau file sudah ada")
    parser.add_argument("--build", action="store_true", help="bangun parquet & ingredient_stats.json (D-06)")
    args = parser.parse_args(argv)
    if not (args.download or args.build):
        parser.print_help()
        return 2
    if args.download:
        try:
            download(force=args.force)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.build:
        if not raw_path().exists():
            print(f"market: {raw_path()} belum ada; jalankan --download dulu.", file=sys.stderr)
            return 1
        started = time.time()
        s = build()
        print(f"market: {s['n_products']:,} produk bersih dalam {time.time() - started:.1f} dtk")
        print(f"  per segmen : {s['n_by_segment']}")
        print(f"  Indonesia  : {s['n_indonesia']:,}")
        print("  prevalensi : " + ", ".join(f"{k}={v:.3f}" for k, v in s["prevalence"].items()))
        print(f"  -> {clean_path()}")
        print(f"  -> {stats_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
