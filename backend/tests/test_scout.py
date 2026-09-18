"""Test Scout literatur (PRD §12.1, §17.1). Pemilik: Nico (D).

Dokumen di sini buatan test (bukan sitasi nyata). Tidak memanggil Europe PMC dan tidak memuat bge-m3.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from fp import scout
from fp.io_utils import read_json

DOCS = [
    {"id": "T1", "pmcid": "PMCTEST1", "doi": None, "title": "[TEST] Carbomer neutralization and gel viscosity",
     "year": 2020, "journal": "[TEST] Journal", "url": "https://europepmc.org/", "query": "t",
     "abstract": "Carbomer gels require neutralization with sodium hydroxide; viscosity rises sharply after neutralization."},
    {"id": "T2", "pmcid": "PMCTEST2", "doi": None, "title": "[TEST] Niacinamide hydrolysis at low pH",
     "year": 2021, "journal": "[TEST] Journal", "url": "https://europepmc.org/", "query": "t",
     "abstract": "Niacinamide converts to nicotinic acid under acidic conditions; formulation pH affects stability. " * 6},
    {"id": "T3", "pmcid": None, "doi": None, "title": "[TEST] Homogenization speed and emulsion droplet size",
     "year": 2019, "journal": "[TEST] Journal", "url": "https://europepmc.org/", "query": "t",
     "abstract": "Higher homogenization speed reduces oil-in-water emulsion droplet size and improves stability."},
    {"id": "T4", "pmcid": "PMCTEST4", "doi": None, "title": "[TEST] Glycerin as humectant",
     "year": 2018, "journal": "[TEST] Journal", "url": "https://europepmc.org/", "query": "t",
     "abstract": "Glycerin improves skin hydration in moisturizer formulations."},
]

FORMULA = {
    "GLYCERIN": 3.0, "NIACINAMIDE": 4.5, "CETEARYL_ALCOHOL": 1.5, "EMULSIFIER": 2.5, "CCT": 5.0,
    "DIMETHICONE": 1.0, "XANTHAN": 0.3, "CARBOMER": 0.3, "NAOH": 0.5, "PHENOXYETHANOL": 0.8,
    "AQUA": 80.6, "RPM": 7000.0, "HMIN": 5.0, "TEMP": 75.0,
}


@pytest.fixture()
def tfidf_index(runtime_dir):
    out = runtime_dir / "scout"
    manifest = scout.build_index(DOCS, out_dir=out, backend="tfidf")
    return {"dir": out, "manifest": manifest, "index": scout.ScoutIndex.load(out)}


def test_missing_index_returns_empty_with_reason(monkeypatch, runtime_dir):
    monkeypatch.setattr(scout, "index_dir", lambda: runtime_dir / "tidak-ada")
    scout.reload()
    try:
        hits = scout.search("carbomer viscosity")
        assert hits == [] and hits.reason == scout.REASON_INDEX_MISSING
        assert scout.status()["ready"] is False
        assert scout.warmup() is False
    finally:
        scout.reload()


def test_status_ready_only_after_warmup(tfidf_index, monkeypatch):
    monkeypatch.setattr(scout, "index_dir", lambda: tfidf_index["dir"])
    scout.reload()
    try:
        before = scout.status()
        assert before["ready"] is False and before["reason"] == scout.REASON_WARMING_UP and before["n_docs"] == 4
        assert scout.search("carbomer viscosity")[0]["id"] == "T1"  # search tetap jalan sebelum warmup
        assert scout.warmup() is True
        assert scout.status()["ready"] is True and "reason" not in scout.status()
    finally:
        scout.reload()


def test_query_for_is_short_english():
    q = scout.query_for(FORMULA)
    assert 1 <= len(q.split()) <= 8
    assert re.fullmatch(r"[a-z ]+", q), q
    # CARBOMER 0,3/0,5 = 60% rentang, EMULSIFIER 2,5/6 = 42%: bahan struktur relatif tertinggi
    assert q.startswith("carbomer glyceryl stearate") and "viscosity" in q and "niacinamide" not in q
    thick_oil = scout.query_for({**FORMULA, "CARBOMER": 0.05, "CCT": 20.0})
    assert thick_oil.startswith("caprylic triglyceride") and thick_oil != q
    assert len(scout.query_for({**FORMULA, "CCT": 20.0, "DIMETHICONE": 5.0, "GLYCERIN": 10.0}).split()) <= 8
    assert scout.query_for({k: 0.0 for k in FORMULA}) == "niacinamide stability cosmetic formulation"


def test_tfidf_fallback_build_and_search(tfidf_index):
    m = tfidf_index["manifest"]
    assert m["backend"] == "tfidf" and m["n_docs"] == 4
    assert not (tfidf_index["dir"] / scout.EMBEDDINGS_NAME).exists()
    assert len(read_json(tfidf_index["dir"] / scout.DOCS_NAME)) == 4

    idx = tfidf_index["index"]
    hits = idx.search("carbomer neutralization viscosity", k=3)
    assert hits.reason is None
    assert hits[0]["id"] == "T1"
    assert set(hits[0]) == {"type", "id", "pmcid", "title", "year", "journal", "url", "score", "snippet"}
    assert hits[0]["type"] == "literature" and 0 < hits[0]["score"] <= 1
    assert idx.search("homogenization droplet size", k=1)[0]["id"] == "T3"


def test_search_limits(tfidf_index):
    idx = tfidf_index["index"]
    assert len(idx.search("stability", k=2)) <= 2
    empty = idx.search("   ")
    assert empty == [] and empty.reason == scout.REASON_EMPTY_QUERY
    long_snippet = idx.search("niacinamide nicotinic acid", k=1)[0]["snippet"]
    assert len(long_snippet) <= scout.SNIPPET_MAX


def test_embedding_failure_falls_back_to_tfidf(monkeypatch):
    idx = scout.ScoutIndex(DOCS, {"backend": "embedding"}, np.ones((4, 3), dtype=np.float32))
    assert idx.backend == "embedding"

    def broken(_device):
        raise ImportError("torch rusak (simulasi test)")

    monkeypatch.setattr(scout, "_load_model", broken)
    hits = idx.search("glycerin humectant", k=1)
    assert idx.backend == "tfidf" and "torch rusak" in idx.fallback_reason
    assert hits[0]["id"] == "T4"


def test_build_index_auto_falls_back_when_embedding_fails(runtime_dir, monkeypatch):
    def broken(texts, device, batch_size=32):
        raise RuntimeError("tanpa GPU/torch (simulasi test)")

    monkeypatch.setattr(scout, "_embed", broken)
    m = scout.build_index(DOCS, out_dir=runtime_dir / "auto", backend="auto", device="cpu")
    assert m["backend"] == "tfidf" and "simulasi" in m["fallback_reason"]


def test_doc_parsing_strips_html_and_requires_abstract():
    r = {"id": "1", "source": "MED", "pmcid": "PMC9", "title": "A <i>test</i> title", "pubYear": "2022",
         "abstractText": "<h4>Background</h4>Carbomer &amp; xanthan.", "journalInfo": {"journal": {"title": "J"}}}
    d = scout._doc_from_result(r, "q")
    assert d["title"] == "A test title" and d["abstract"] == "Background Carbomer & xanthan."
    assert d["year"] == 2022 and d["url"].endswith("/PMC/PMC9") and d["journal"] == "J"
    assert scout._doc_from_result({**r, "abstractText": ""}, "q") is None


def test_evidence(tfidf_index):
    hit = tfidf_index["index"].search("carbomer", k=1)[0]
    ev = scout.evidence(hit)
    assert ev.type == "literature" and ev.source == "Europe PMC"
    assert ev.title == hit["title"] and ev.detail["pmcid"] == "PMCTEST1"
    assert len(ev.detail["snippet"]) <= scout.SNIPPET_MAX
