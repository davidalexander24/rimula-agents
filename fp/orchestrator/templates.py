"""Teks deterministik: ringkasan kandidat, rekomendasi, judul bukti pasar (PRD §12.2, §13.6, §15.5). Pemilik: David (B).

Angka di dalam kalimat memakai format Indonesia (6.935 cP, pH 5,6) karena frontend menampilkan teks apa adanya.
Angka terstruktur (field JSON) tetap numerik dan diformat frontend (§13.6).
"""

from __future__ import annotations

from typing import Iterable, Optional

from fp import schemas as S

STATUS_LABEL = {"pass": "Lolos pemeriksaan", "review": "Perlu ditinjau", "blocked": "Diblokir"}

MAX_ISSUES_IN_SUMMARY = 2

SUMMARY_TEMPLATE = (
    "Prediksi viskositas {visc} cP (95%: {visc_lo}–{visc_hi}), pH {ph}, droplet {d50} µm, "
    "peluang stabil {p_stable}. Peluang memenuhi seluruh spesifikasi {p_target}; biaya bahan Rp{cost}/kg (harga asumsi). "
    "Guardian: {status_label}{issue_text}."
)


def fmt_id(value: float, decimals: int = 0) -> str:
    """6935.2 → '6.935'; 5.61 (1 desimal) → '5,6'."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pct_id(value: float) -> str:
    return f"{fmt_id(value * 100, 0)}%"


def issue_text(gate: S.Gate) -> str:
    messages = [i.message.rstrip(". ") for i in gate.issues if i.severity in ("error", "warning")]
    if not messages:
        return ""
    shown = "; ".join(messages[:MAX_ISSUES_IN_SUMMARY])
    extra = len(messages) - MAX_ISSUES_IN_SUMMARY
    if extra > 0:
        shown += f"; dan {extra} catatan lain"
    return f" ({shown})"


def summary_text(prediction: Optional[S.Prediction], gate: S.Gate) -> str:
    label = STATUS_LABEL.get(gate.status, gate.status)
    if prediction is None:
        return f"Prediksi belum tersedia. Guardian: {label}{issue_text(gate)}."
    lo, hi = prediction.VISCOSITY_CP_CI95
    return SUMMARY_TEMPLATE.format(
        visc=fmt_id(prediction.VISCOSITY_CP),
        visc_lo=fmt_id(lo),
        visc_hi=fmt_id(hi),
        ph=fmt_id(prediction.PH, 1),
        d50=fmt_id(prediction.D50_UM, 1),
        p_stable=pct_id(prediction.P_STABLE),
        p_target=pct_id(prediction.P_TARGET),
        cost=fmt_id(prediction.COST_IDR_PER_KG),
        status_label=label,
        issue_text=issue_text(gate),
    )


def template_summary(candidate: S.Candidate, reason: Optional[str] = None) -> S.Summary:
    return S.Summary(text=summary_text(candidate.prediction, candidate.gate), source="template", reason=reason)


def recommendation(candidates: Iterable[S.Candidate]) -> str:
    usable = [c for c in candidates if c.gate.status != "blocked"]
    if not usable:
        return "Semua kandidat diblokir Guardian. Ubah spesifikasi atau jalankan ulang."
    usable.sort(key=lambda c: (-(c.prediction.P_TARGET if c.prediction else -1.0), c.rank))
    order = ", ".join(f"#{c.rank}" for c in usable)
    return f"Urutan uji yang disarankan menurut peluang memenuhi spesifikasi: kandidat {order}. Keputusan tetap pada formulator."


def market_title(n_products_all: int, n_indonesia: int) -> str:
    return (
        f"Kombinasi bahan ini ditemukan pada {n_products_all} produk skincare/makeup (Open Beauty Facts), "
        f"termasuk {n_indonesia} produk di Indonesia."
    )
