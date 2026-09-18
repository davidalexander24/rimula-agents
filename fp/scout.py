"""Scout literatur: bukti Europe PMC open access (PRD §12.1). Pemilik: Nico (D).

    python -m fp.scout --build                 # unduh abstrak + embedding bge-m3 -> artifacts/scout/
    python -m fp.scout --build --backend tfidf # tanpa torch (fallback)
    python -m fp.scout --search "carbomer neutralization viscosity"

    from fp import scout
    scout.warmup()                                        # backend: muat indeks & model query sekali
    hits = scout.search(scout.query_for(formula), k=3)    # Hits (list) + hits.reason
    [scout.evidence(h) for h in hits]                     # fp.schemas.Evidence

Backend `embedding` = BAAI/bge-m3 (build di SCOUT_BUILD_DEVICE, query di SCOUT_QUERY_DEVICE).
Jika torch/sentence-transformers gagal, pencarian otomatis memakai TF-IDF atas dokumen yang sama.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

import numpy as np

from fp.schemas import INGREDIENT_FIELDS, Evidence

SOURCE = "Europe PMC"
EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
MODEL_NAME = "BAAI/bge-m3"
QUERIES = (
    "niacinamide topical formulation stability",
    "carbomer neutralization viscosity cosmetic",
    "oil-in-water emulsion droplet size homogenization",
    "emulsion stability viscosity droplet size cosmetic cream",
    "xanthan gum cosmetic emulsion rheology",
    "cetearyl alcohol emulsion stability",
    "glycerin humectant skin moisturizer formulation",
    "phenoxyethanol preservative cosmetic",
)
PAGE_SIZE = 100
MIN_DOCS = 150
ABSTRACT_EMBED_CHARS = 2000
MAX_SEQ_LENGTH = 512
MAX_QUERY_WORDS = 8
MAX_QUERY_CHARS = 200
SNIPPET_MAX = 300

DOCS_NAME = "docs.json"
EMBEDDINGS_NAME = "embeddings.npy"
MANIFEST_NAME = "index_manifest.json"

REASON_INDEX_MISSING = "scout_index_missing"
REASON_EMPTY_QUERY = "empty_query"
REASON_WARMING_UP = "scout_warming_up"

DOC_FIELDS = ("id", "pmcid", "doi", "title", "year", "journal", "abstract", "url", "query")

# Nama INCI bahasa Inggris dan kata kunci peran/sifat untuk kueri literatur.
TERMS: dict[str, tuple[str, str]] = {
    "GLYCERIN": ("glycerin", "humectant"),
    "NIACINAMIDE": ("niacinamide", "stability"),
    "CETEARYL_ALCOHOL": ("cetearyl alcohol", "emulsion"),
    "EMULSIFIER": ("glyceryl stearate", "emulsion"),
    "CCT": ("caprylic triglyceride", "emulsion"),
    "DIMETHICONE": ("dimethicone", "emollient"),
    "XANTHAN": ("xanthan gum", "rheology"),
    "CARBOMER": ("carbomer", "viscosity"),
    "NAOH": ("sodium hydroxide", "neutralization"),
    "PHENOXYETHANOL": ("phenoxyethanol", "preservative"),
}

PathLike = Union[str, Path]


STRUCTURAL = ("GLYCERIN", "CETEARYL_ALCOHOL", "EMULSIFIER", "CCT", "DIMETHICONE", "XANTHAN", "CARBOMER")
RISK_KEYWORDS: dict[str, str] = {
    "GLYCERIN": "humectant moisturizer",
    "CETEARYL_ALCOHOL": "emulsion viscosity",
    "EMULSIFIER": "emulsion stability",
    "CCT": "emulsion droplet size",
    "DIMETHICONE": "emulsion stability",
    "XANTHAN": "rheology viscosity",
    "CARBOMER": "neutralization viscosity",
}


def _palette_max() -> dict[str, float]:
    global _PALETTE_MAX
    if _PALETTE_MAX is None:
        try:
            from fp import palette

            _PALETTE_MAX = {k: float(hi) for k, (_, hi) in palette.bounds().items()}
        except Exception:  # palet belum ada -> pakai % mutlak
            _PALETTE_MAX = {}
    return _PALETTE_MAX


_PALETTE_MAX: Optional[dict[str, float]] = None


class Hits(list):
    """Daftar bukti literatur dengan `reason` (None bila pencarian berjalan normal)."""

    def __init__(self, items: Any = (), reason: Optional[str] = None):
        super().__init__(items)
        self.reason = reason


# ---------------------------------------------------------------- path & setelan


def _settings():
    from fp.config import get_settings

    return get_settings()


def index_dir() -> Path:
    return _settings().scout_artifacts_dir


# ---------------------------------------------------------------- kueri


def query_for(formula: Any) -> str:
    """Kueri bahasa Inggris ≤ 8 kata: 2 bahan struktur dengan kadar tertinggi RELATIF terhadap rentang palet
    + kata kunci risiko bahan teratas + "cream".

    Niacinamide, pengawet, dan pH adjuster tidak dipakai: ketiganya sama di hampir semua kandidat brief sehingga
    kueri (dan bukti) menjadi identik (temuan david-1935). Formula tanpa bahan struktur -> kueri niacinamide.
    """
    f = formula.model_dump() if hasattr(formula, "model_dump") else dict(formula)
    maxima = _palette_max()
    ranked = sorted(
        (k for k in STRUCTURAL if float(f.get(k, 0.0) or 0.0) > 0),
        key=lambda k: (-float(f.get(k, 0.0) or 0.0) / (maxima.get(k) or 1.0), k),
    )[:2]
    if not ranked:
        return "niacinamide stability cosmetic formulation"
    words: list[str] = []
    for code in ranked:
        words.extend(TERMS[code][0].split())
    for w in RISK_KEYWORDS[ranked[0]].split() + ["cream"]:
        if w not in words:
            words.append(w)
    return " ".join(words[:MAX_QUERY_WORDS])


# ---------------------------------------------------------------- build


def fetch_docs(queries: Iterable[str] = QUERIES, page_size: int = PAGE_SIZE, retries: int = 3) -> list[dict[str, Any]]:
    """Ambil abstrak open access dari Europe PMC; wajib abstractText; dedup pmcid/id."""
    import requests

    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in queries:
        params = {"query": f"{q} AND OPEN_ACCESS:y", "format": "json", "resultType": "core", "pageSize": page_size}
        results = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(EUROPEPMC_URL, params=params, timeout=(15, 60))
                resp.raise_for_status()
                results = resp.json().get("resultList", {}).get("result", [])
                break
            except Exception as exc:
                print(f"scout: kueri '{q}' percobaan {attempt}/{retries} gagal: {exc}", file=sys.stderr)
                time.sleep(3 * attempt)
        if results is None:
            continue
        added = 0
        for r in results:
            doc = _doc_from_result(r, q)
            if doc is None:
                continue
            key = doc["pmcid"] or f"{r.get('source', '')}:{doc['id']}"
            if key in seen:
                continue
            seen.add(key)
            docs.append(doc)
            added += 1
        print(f"scout: '{q}' -> {len(results)} hasil, {added} dokumen baru")
    return docs


def build_index(
    docs: list[Mapping[str, Any]],
    out_dir: Optional[PathLike] = None,
    backend: str = "auto",
    device: Optional[str] = None,
) -> dict[str, Any]:
    """Tulis docs.json, embeddings.npy (backend embedding), index_manifest.json. Mengembalikan manifest."""
    from fp.config import now_iso
    from fp.io_utils import write_json, write_npy

    out = Path(out_dir) if out_dir else index_dir()
    out.mkdir(parents=True, exist_ok=True)
    docs = [{k: d.get(k) for k in DOC_FIELDS} for d in docs]
    manifest: dict[str, Any] = {
        "built_at": now_iso(),
        "source": SOURCE,
        "queries": list(QUERIES),
        "n_docs": len(docs),
        "backend": "tfidf",
        "model": None,
        "dim": None,
        "device": None,
        "fallback_reason": None,
    }
    embeddings = None
    if backend in ("auto", "embedding"):
        device = device or _settings().scout_build_device
        try:
            started = time.time()
            embeddings, used_device = _embed([_doc_text(d) for d in docs], device=device, batch_size=32)
            manifest.update(backend="embedding", model=MODEL_NAME, dim=int(embeddings.shape[1]), device=used_device)
            manifest["embed_seconds"] = round(time.time() - started, 1)
        except Exception as exc:
            if backend == "embedding":
                raise
            manifest["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"scout: embedding gagal, pakai TF-IDF: {manifest['fallback_reason']}", file=sys.stderr)

    write_json(out / DOCS_NAME, docs)
    if embeddings is not None:
        write_npy(out / EMBEDDINGS_NAME, embeddings.astype(np.float32))
    else:
        (out / EMBEDDINGS_NAME).unlink(missing_ok=True)
    write_json(out / MANIFEST_NAME, manifest)
    reload()
    return manifest


def build(backend: str = "auto", device: Optional[str] = None) -> dict[str, Any]:
    docs = fetch_docs()
    if not docs:
        raise RuntimeError("Europe PMC tidak mengembalikan dokumen (cek koneksi VPS)")
    if len(docs) < MIN_DOCS:
        print(f"scout: PERINGATAN hanya {len(docs)} dokumen (< {MIN_DOCS})", file=sys.stderr)
    return build_index(docs, backend=backend, device=device)


# ---------------------------------------------------------------- indeks & pencarian


class ScoutIndex:
    """Indeks yang dimuat sekali. Embedding bila tersedia, TF-IDF sebagai cadangan."""

    def __init__(self, docs: list[dict[str, Any]], manifest: Mapping[str, Any], embeddings: Optional[np.ndarray]):
        self.docs = docs
        self.manifest = dict(manifest)
        self.embeddings = embeddings
        self.backend = "embedding" if embeddings is not None and manifest.get("backend") == "embedding" else "tfidf"
        self.fallback_reason: Optional[str] = None
        self.warm = False
        self._model = None
        self._tfidf = None
        self._tfidf_matrix = None
        self._lock = threading.Lock()

    @classmethod
    def load(cls, directory: PathLike) -> "ScoutIndex":
        from fp.io_utils import read_json

        d = Path(directory)
        manifest = read_json(d / MANIFEST_NAME)
        docs = read_json(d / DOCS_NAME)
        emb_path = d / EMBEDDINGS_NAME
        embeddings = np.load(emb_path) if manifest.get("backend") == "embedding" and emb_path.exists() else None
        if embeddings is not None and len(embeddings) != len(docs):
            embeddings = None
        return cls(docs, manifest, embeddings)

    def warmup(self) -> None:
        """Muat model query (±33 dtk di CPU) + satu encode pemanasan; setelah ini `warm=True`."""
        if self.backend == "embedding":
            try:
                self._query_model().encode(["warmup"], normalize_embeddings=True, convert_to_numpy=True)
            except Exception as exc:  # torch rusak -> TF-IDF
                self.backend = "tfidf"
                self.fallback_reason = f"{type(exc).__name__}: {exc}"[:300]
        if self.backend == "tfidf":
            self._tfidf_fit()
        self.warm = True

    def search(self, query: str, k: int = 3) -> Hits:
        query = " ".join(str(query or "").split())[:MAX_QUERY_CHARS]
        if not query:
            return Hits([], reason=REASON_EMPTY_QUERY)
        if not self.docs:
            return Hits([], reason=REASON_INDEX_MISSING)
        k = max(1, min(int(k), 10))
        scores = None
        if self.backend == "embedding":
            try:
                model = self._query_model()
                q = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)
                scores = self.embeddings @ q
            except Exception as exc:  # torch rusak saat query -> TF-IDF
                self.backend = "tfidf"
                self.fallback_reason = f"{type(exc).__name__}: {exc}"[:300]
                print(f"scout: query embedding gagal, pindah ke TF-IDF: {self.fallback_reason}", file=sys.stderr)
        if scores is None:
            from sklearn.metrics.pairwise import linear_kernel

            vec, matrix = self._tfidf_fit()
            scores = linear_kernel(vec.transform([query]), matrix).ravel()
        order = np.argsort(-scores)[:k]
        return Hits([self._hit(int(i), float(scores[i])) for i in order if scores[i] > 0])

    def _hit(self, i: int, score: float) -> dict[str, Any]:
        d = self.docs[i]
        return {
            "type": "literature",
            "id": d.get("id"),
            "pmcid": d.get("pmcid"),
            "title": d.get("title"),
            "year": d.get("year"),
            "journal": d.get("journal"),
            "url": d.get("url"),
            "score": round(score, 4),
            "snippet": _snippet(d.get("abstract") or ""),
        }

    def _query_model(self):
        with self._lock:
            if self._model is None:
                device = _settings().scout_query_device
                self._model = _load_model(device)
            return self._model

    def _tfidf_fit(self):
        with self._lock:
            if self._tfidf is None:
                from sklearn.feature_extraction.text import TfidfVectorizer

                self._tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
                self._tfidf_matrix = self._tfidf.fit_transform([_doc_text(d) for d in self.docs])
            return self._tfidf, self._tfidf_matrix


_lock = threading.Lock()
_index: Optional[ScoutIndex] = None
_index_key: Optional[float] = None


def _get_index() -> Optional[ScoutIndex]:
    global _index, _index_key
    d = index_dir()
    try:
        key = (d / MANIFEST_NAME).stat().st_mtime
        (d / DOCS_NAME).stat()
    except FileNotFoundError:
        return None
    with _lock:
        if _index is None or _index_key != key:
            try:
                _index, _index_key = ScoutIndex.load(d), key
            except Exception as exc:
                print(f"scout: gagal memuat indeks: {exc}", file=sys.stderr)
                _index, _index_key = None, None
        return _index


def reload() -> None:
    global _index, _index_key
    with _lock:
        _index, _index_key = None, None


def status() -> dict[str, Any]:
    """`ready`, `n_docs`, `built_at` (+ `backend`, atau `reason` bila belum siap).

    `ready` baru True setelah `warmup()` selesai, agar backend tidak memanggil `search()` yang menunggu model
    dimuat ±30 dtk (temuan smoke test 20:52). `search()` sendiri tetap bisa dipanggil kapan saja.
    """
    idx = _get_index()
    if idx is None:
        return {"ready": False, "n_docs": 0, "built_at": None, "reason": REASON_INDEX_MISSING}
    out = {"ready": idx.warm, "n_docs": len(idx.docs), "built_at": idx.manifest.get("built_at"), "backend": idx.backend}
    if not idx.warm:
        out["reason"] = REASON_WARMING_UP
    return out


def warmup() -> bool:
    """Muat indeks dan model query (dipanggil backend di thread latar). True bila siap."""
    idx = _get_index()
    if idx is None:
        return False
    idx.warmup()
    return True


def search(query: str, k: int = 3) -> Hits:
    """Top-k bukti `type="literature"`: id, pmcid, title, year, journal, url, score, snippet."""
    idx = _get_index()
    if idx is None:
        return Hits([], reason=REASON_INDEX_MISSING)
    return idx.search(query, k)


def evidence(hit: Mapping[str, Any]) -> Evidence:
    """Ubah satu hasil `search()` menjadi Evidence untuk kandidat."""
    detail = {k: hit.get(k) for k in ("id", "pmcid", "year", "journal", "url", "score")}
    detail["snippet"] = str(hit.get("snippet") or "")[:SNIPPET_MAX]
    return Evidence(type="literature", title=str(hit.get("title") or ""), detail=detail, source=SOURCE)


# ---------------------------------------------------------------- helper


def _clean(text: Any) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    return " ".join(s.split())


def _doc_from_result(r: Mapping[str, Any], query: str) -> Optional[dict[str, Any]]:
    abstract = _clean(r.get("abstractText"))
    title = _clean(r.get("title"))
    if not abstract or not title:
        return None
    pmcid = r.get("pmcid") or None
    source, rid = r.get("source") or "", str(r.get("id") or "")
    journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title") or r.get("journalTitle")
    year = r.get("pubYear")
    url = f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else f"https://europepmc.org/article/{source}/{rid}"
    return {
        "id": rid,
        "pmcid": pmcid,
        "doi": r.get("doi") or None,
        "title": title,
        "year": int(year) if str(year or "").isdigit() else None,
        "journal": journal,
        "abstract": abstract,
        "url": url,
        "query": query,
    }


def _doc_text(d: Mapping[str, Any]) -> str:
    return f"{d.get('title') or ''}. {(d.get('abstract') or '')[:ABSTRACT_EMBED_CHARS]}"


def _snippet(abstract: str) -> str:
    if len(abstract) <= SNIPPET_MAX:
        return abstract
    cut = abstract[: SNIPPET_MAX - 1]
    cut = cut[: cut.rfind(" ")] if " " in cut else cut
    return cut + "…"


def _load_model(device: str):
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {}
    if device.startswith("cuda"):
        import torch

        kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
    model = SentenceTransformer(MODEL_NAME, device=device, **kwargs)
    model.max_seq_length = MAX_SEQ_LENGTH
    return model


def _embed(texts: list[str], device: str, batch_size: int = 32) -> tuple[np.ndarray, str]:
    """Embedding dokumen; cuda gagal -> cpu."""
    if device.startswith("cuda"):
        try:
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError("cuda tidak tersedia")
            model = _load_model(device)
            emb = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
            del model
            torch.cuda.empty_cache()
            return np.asarray(emb, dtype=np.float32), device
        except Exception as exc:
            print(f"scout: embedding di {device} gagal ({exc}); coba cpu", file=sys.stderr)
    model = _load_model("cpu")
    emb = model.encode(texts, batch_size=8, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(emb, dtype=np.float32), "cpu"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fp.scout", description="Indeks literatur Europe PMC")
    parser.add_argument("--build", action="store_true", help="bangun artifacts/scout/*")
    parser.add_argument("--backend", choices=("auto", "embedding", "tfidf"), default="auto")
    parser.add_argument("--device", default=None, help="override SCOUT_BUILD_DEVICE")
    parser.add_argument("--search", metavar="KUERI", help="uji pencarian pada indeks yang ada")
    parser.add_argument("-k", type=int, default=3)
    args = parser.parse_args(argv)
    if not (args.build or args.search):
        parser.print_help()
        return 2
    if args.build:
        started = time.time()
        try:
            m = build(backend=args.backend, device=args.device)
        except RuntimeError as exc:
            print(f"scout: {exc}", file=sys.stderr)
            return 1
        print(f"scout: {m['n_docs']} dokumen, backend {m['backend']} ({m.get('device')}) dalam {time.time() - started:.1f} dtk")
        print(f"  -> {index_dir()}")
    if args.search:
        started = time.time()
        hits = search(args.search, k=args.k)
        print(f"scout: '{args.search}' -> {len(hits)} hasil ({time.time() - started:.2f} dtk, reason={hits.reason})")
        for h in hits:
            print(f"  {h['score']:.3f}  {h['year']}  {h['pmcid'] or h['id']}  {h['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
