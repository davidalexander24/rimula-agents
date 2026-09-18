"""Test Market / Scout pasar (PRD §8.3, §12.2, §17.1). Pemilik: Nico (D).

Semua data di sini buatan test (bukan data OBF asli) dan ditulis ke var/test/<nama>/ (R22).
"""

from __future__ import annotations

import gzip
import time

import pytest

from fp import guardian, market
from fp.io_utils import read_json

HEADER = market.KEY_COLUMNS + ["extra_column"]
FIELDS = ["code", "product_name", "brands", "categories_tags", "countries_tags", "ingredients_text", "ingredients_tags"]

PRODUCTS = [
    ("001", "Krim Wajah A", "Merek Uji", "en:face,en:facial-creams", "en:indonesia",
     "Aqua, Glycerin, Niacinamide, Carbomer, Sodium Hydroxide", ""),
    ("002", "Creme B", "Marque Test", "en:facial-creams", "en:france",
     "Water, Glycerol, Nicotinamide, Cetearyl Alcohol, Parfum", ""),
    ("003", "Foundation C", "Brand C", "en:cosmetic-products,en:makeup", "en:germany",
     "Dimethicone, Caprylic/Capric Triglyceride, Glycerin, Talc", ""),
    ("004", "Sunscreen D", "Brand D", "en:suncare,en:sunscreen", "en:australia",
     "Aqua, Niacinamide, Glycerin, Phenoxyethanol, Zinc Oxide", ""),
    ("005", "Shampoo E", "Brand E", "en:cosmetic-products,en:shampoos", "en:indonesia",
     "Aqua, Glycerin, Sodium Laureth Sulfate, Niacinamide", ""),
    ("006", "Short F", "Brand F", "en:moisturizers", "en:france", "glycerin", ""),
    ("007", "Juice G", "Brand G", "en:beverages", "en:indonesia", "water, glycerin, sugar, niacinamide", ""),
    ("008", "Serum H", "Brand H", "en:serums", "en:italy",
     "Aqua, Polyglycerin-10, Xanthan Gum, Phenoxyethanol", ""),
    ("009", "Lotion I", "Brand I", "en:moisturizers", "en:spain",
     "see list on the packaging of this product", "en:caprylic-capric-triglyceride,fr:dimethicone"),
    ("001", "Krim Wajah A duplikat", "Merek Uji", "en:face", "en:indonesia",
     "Aqua, Glycerin, Niacinamide, Carbomer, Sodium Hydroxide", ""),
]


@pytest.fixture()
def mini(runtime_dir):
    raw = runtime_dir / "obf_mini.csv.gz"
    lines = ["\t".join(HEADER)]
    for p in PRODUCTS:
        row = dict(zip(FIELDS, p), main_category="", extra_column="x")
        lines.append("\t".join(row[c] for c in HEADER))
    with gzip.open(raw, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    parquet = runtime_dir / "clean.parquet"
    stats_file = runtime_dir / "ingredient_stats.json"
    stats_obj = market.build(raw=raw, out_parquet=parquet, out_stats=stats_file)
    return {"stats": stats_obj, "index": market.MarketIndex.load(parquet, stats_file), "stats_file": stats_file}


@pytest.fixture(scope="module")
def patterns():
    return market.compile_patterns(market.load_synonyms())


def codes_in(text, patterns, tags=""):
    return market.map_codes(market.normalize_ingredients(text, tags), patterns)


def test_synonym_mapping(patterns):
    assert codes_in("Water, Glycerol, Nicotinamide", patterns) == ["GLYCERIN", "NIACINAMIDE"]
    assert codes_in("CAPRYLIC/CAPRIC TRIGLYCERIDE, Cetostearyl Alcohol", patterns) == ["CCT", "CETEARYL_ALCOHOL"]
    assert codes_in("Glyceryl Stearate, PEG-100 Stearate, Xanthan Gum", patterns) == ["EMULSIFIER", "XANTHAN"]
    assert codes_in("Sodium Hydroxide, Carbomer, Phenoxyethanol, Dimethicone", patterns) == [
        "CARBOMER", "DIMETHICONE", "NAOH", "PHENOXYETHANOL",
    ]


def test_synonym_whole_word_only(patterns):
    assert "GLYCERIN" not in codes_in("Aqua, Polyglycerin-10, Glyceryl Caprylate", patterns)
    assert "DIMETHICONE" not in codes_in("Cyclopentasiloxane, Amodimethicone", patterns)


def test_tags_are_used(patterns):
    assert codes_in("", patterns, tags="en:caprylic-capric-triglyceride,fr:dimethicone") == ["CCT", "DIMETHICONE"]


def test_segment_rules():
    assert market.segment_of("en:face,en:facial-creams") == "skincare"
    assert market.segment_of("en:cosmetic-products,en:makeup") == "makeup"
    assert market.segment_of("en:suncare,en:face") == "suncare"
    assert market.segment_of("en:cosmetic-products,en:shampoos") is None
    assert market.segment_of("en:beverages") is None
    assert market.segment_of("") is None


def test_build_counts(mini):
    s = mini["stats"]
    # 001, 002, 003, 004, 008, 009 (005 shampoo, 006 terlalu pendek, 007 bukan kosmetik, 001 duplikat)
    assert s["n_products"] == 6
    assert s["n_by_segment"] == {"skincare": 4, "makeup": 1, "suncare": 1}
    assert s["n_indonesia"] == 1
    assert s["source"] == "Open Beauty Facts" and s["license"] == "ODbL"
    assert s["pair_support"]["GLYCERIN|NIACINAMIDE"] == 3
    assert s["prevalence"]["GLYCERIN"] == pytest.approx(4 / 6, abs=1e-6)
    assert s["prevalence"]["XANTHAN"] == pytest.approx(1 / 6, abs=1e-6)
    assert len(s["pair_support"]) == 45
    assert read_json(mini["stats_file"])["n_products"] == 6


def test_support(mini):
    r = mini["index"].support(["niacinamide", "GLYCERIN", "AQUA"])
    assert r["type"] == "market" and r["reason"] is None
    assert r["codes"] == ["GLYCERIN", "NIACINAMIDE"]
    assert r["n_products_all"] == 3
    assert r["n_by_segment"] == {"skincare": 2, "makeup": 0, "suncare": 1}
    assert r["n_indonesia"] == 1
    assert r["min_pair_support"] == 3 and r["weakest_pair"] == "GLYCERIN|NIACINAMIDE"
    assert 1 <= len(r["examples"]) <= 3
    assert r["examples"][0]["product_name"] == "Krim Wajah A"  # Indonesia didahulukan
    assert set(r["examples"][0]) == {"product_name", "brands", "segment"}


def test_support_combination_and_weakest_pair(mini):
    r = mini["index"].support(["GLYCERIN", "NIACINAMIDE", "CARBOMER"])
    assert r["n_products_all"] == 1
    assert r["weakest_pair"] in {"CARBOMER|GLYCERIN", "CARBOMER|NIACINAMIDE"} and r["min_pair_support"] == 1
    none = mini["index"].support(["XANTHAN", "CARBOMER"])
    assert none["n_products_all"] == 0 and none["examples"] == []


def test_support_no_codes(mini):
    r = mini["index"].support(["AQUA"])
    assert r["reason"] == market.REASON_NO_CODES and r["n_products_all"] == 0
    assert market.evidence(r) is None


def test_support_speed(mini):
    idx = mini["index"]
    started = time.perf_counter()
    for _ in range(100):
        idx.support(["NIACINAMIDE", "GLYCERIN", "CARBOMER", "PHENOXYETHANOL"])
    assert (time.perf_counter() - started) / 100 < 0.2


def test_evidence(mini):
    ev = market.evidence(mini["index"].support(["GLYCERIN", "NIACINAMIDE"]))
    assert ev.type == "market" and ev.source == "Open Beauty Facts"
    assert ev.title == (
        "Kombinasi bahan ini ditemukan pada 3 produk skincare/makeup (Open Beauty Facts), termasuk 1 produk di Indonesia."
    )
    assert ev.detail["n_products_all"] == 3
    zero = market.evidence(mini["index"].support(["XANTHAN", "CARBOMER"]))
    assert "belum ditemukan" in zero.title


def test_not_ready_when_artifacts_missing(monkeypatch, runtime_dir):
    monkeypatch.setattr(market, "clean_path", lambda: runtime_dir / "missing.parquet")
    monkeypatch.setattr(market, "stats_path", lambda: runtime_dir / "missing.json")
    market.reload()
    try:
        assert market.status()["ready"] is False
        r = market.support(["GLYCERIN"])
        assert r["reason"] == market.REASON_NOT_READY and r["n_products_all"] == 0
        assert market.stats() is None and market.prevalence() == {}
    finally:
        market.reload()


def test_guardian_uses_market_stats(mini):
    formula = {
        "GLYCERIN": 3.0, "NIACINAMIDE": 4.5, "CETEARYL_ALCOHOL": 0.0, "EMULSIFIER": 0.0, "CCT": 0.0,
        "DIMETHICONE": 0.0, "XANTHAN": 0.3, "CARBOMER": 0.0, "NAOH": 0.0, "PHENOXYETHANOL": 0.8,
        "AQUA": 91.4, "RPM": 7000.0, "HMIN": 5.0, "TEMP": 75.0,
    }
    ctx = guardian.build_context(None, bounds={}, regulatory=None, unc_max=None, market=mini["stats"])
    gate = guardian.check(formula, None, ctx)
    uncommon = [i for i in gate.issues if i.code == "UNCOMMON_COMBINATION"]
    assert len(uncommon) == 1 and uncommon[0].severity == "info"
    assert "OBF: 0" in uncommon[0].message
