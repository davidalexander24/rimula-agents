"""Validasi ringkasan LLM: angka harus berasal dari hasil tool, tanpa klaim terlarang (PRD §13.5). Pemilik: David (B)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

NUMBER_RE = re.compile(r"(?<![A-Za-z_\d])(?<!\d[.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)")
CURRENCY_RE = re.compile(r"(?i)\b(rp|idr)\.?\s*(?=\d)")

FORBIDDEN_WORDS = ("halal", "aman", "bpom", "dijamin", "terbaik", "pasti")
CLAUSE_SPLIT_RE = re.compile(r"[.!?;,:\n()]+")
TOKEN_RE = re.compile(r"[a-z0-9%#]+")
NEGATIONS = frozenset({"tidak", "bukan", "belum", "tanpa", "jangan"})
NEGATION_WINDOW = 3
TOPIC_WINDOW = 2
VERIFY_WINDOW = 4
AFTER_WINDOW = 3
TOPIC_BEFORE = {
    "halal": frozenset({
        "peringatan", "catatan", "risiko", "status", "sertifikat", "sertifikasi", "verifikasi", "pemeriksaan", "cek",
        "aspek", "isu", "kepatuhan", "persyaratan", "kriteria", "sumber", "label", "klaim", "kritis", "titik", "audit",
    }),
    "bpom": frozenset({
        "batas", "regulasi", "ketentuan", "peraturan", "aturan", "persyaratan", "standar", "ke", "pendaftaran",
        "notifikasi", "registrasi", "kepatuhan", "verifikasi", "cek", "status", "acuan",
    }),
    "aman": frozenset({"batas", "apakah"}),
}
VERIFY_BEFORE = frozenset({
    "perlu", "harus", "wajib", "cek", "dicek", "periksa", "diperiksa", "verifikasi", "diverifikasi", "konfirmasi",
    "dikonfirmasi", "pastikan", "sertifikat", "sertifikasi", "pemasok",
})
AFTER_CUES = frozenset({"dicek", "diperiksa", "diverifikasi", "dikonfirmasi", "dipastikan", "pemasok", "belum", "asumsi", "perlu"})
HARD_CLAIM_RES = (
    re.compile(r"\blolos\s+(uji\s+)?bpom\b"),
    re.compile(r"\b(sudah|pasti|dijamin|terjamin|100\s*%?)\s+(halal|aman)\b"),
    re.compile(r"\b(halal|aman)\s+(dan|&)\s+(halal|aman)\b"),
)
OVERCLAIM_RE = re.compile(r"\b(sudah |telah )?memenuhi (semua|seluruh) (spesifikasi|target)")
OVERCLAIM_WINDOW = 30

ALWAYS_ALLOWED = (95.0,)
MAX_DECIMALS = 2


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    offending: list[str] = field(default_factory=list)


def _interpretations(token: str) -> list[tuple[float, int]]:
    """Semua cara membaca token angka: desimal titik/koma dan pemisah ribuan Indonesia/Inggris."""
    out: list[tuple[float, int]] = []
    seps = [c for c in token if c in ".,"]
    if not seps:
        return [(float(token), 0)]
    if len(set(seps)) == 2:
        dec = token[max(token.rfind("."), token.rfind(","))]
        thou = "," if dec == "." else "."
        whole, frac = token.replace(thou, "").split(dec)
        return [(float(f"{whole}.{frac}"), len(frac))]
    sep = seps[0]
    parts = token.split(sep)
    if len(parts) > 2:
        return [(float("".join(parts)), 0)]
    whole, frac = parts
    out.append((float(f"{whole}.{frac}"), len(frac)))
    if len(frac) == 3:
        out.append((float(whole + frac), 0))
    return out


def extract_numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(CURRENCY_RE.sub(r"\1 ", text or ""))


def collect_numbers(*objs: Any) -> set[float]:
    """Kumpulkan semua nilai numerik (termasuk angka di dalam string) dari hasil tool."""
    found: set[float] = set()

    def walk(o: Any) -> None:
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            if math.isfinite(float(o)):
                found.add(float(o))
            return
        if isinstance(o, str):
            for tok in extract_numbers(o):
                for value, _ in _interpretations(tok):
                    found.add(value)
            return
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
            return
        if isinstance(o, (list, tuple, set)):
            for v in o:
                walk(v)
            return
        if hasattr(o, "model_dump"):
            walk(o.model_dump(mode="json"))

    for obj in objs:
        walk(obj)
    return found


def _scaled(values: Iterable[float]) -> list[float]:
    out: list[float] = []
    for v in list(values) + list(ALWAYS_ALLOWED):
        out.extend((v, v * 100.0))
    return out


def _is_legit(token: str, scaled: list[float]) -> bool:
    """Token sah jika ada nilai tool (atau ×100 untuk persen) yang dibulatkan ke presisi token sama dengan token."""
    for value, decimals in _interpretations(token):
        if decimals > MAX_DECIMALS + 1:
            continue
        tol = 1e-9 * max(1.0, abs(value))
        if any(abs(round(s, decimals) - value) < tol for s in scaled):
            return True
    return False


def check_numbers(text: str, allowed: Iterable[float]) -> Verdict:
    scaled = _scaled(allowed)
    bad = [tok for tok in extract_numbers(text) if not _is_legit(tok, scaled)]
    if bad:
        return Verdict(False, "number", bad)
    return Verdict(True)


def _claim_allowed(word: str, tokens: list[str], i: int) -> bool:
    """Kata terlarang hanya boleh dalam konteks peringatan/verifikasi atau negasi, bukan sebagai klaim (§13.5 butir 4)."""
    before = tokens[max(0, i - NEGATION_WINDOW) : i]
    if any(t in NEGATIONS for t in before):
        return True
    if word not in TOPIC_BEFORE:
        return False
    if any(t in TOPIC_BEFORE[word] for t in tokens[max(0, i - TOPIC_WINDOW) : i]):
        return True
    if word == "aman":
        return False
    if any(t in VERIFY_BEFORE for t in tokens[max(0, i - VERIFY_WINDOW) : i]):
        return True
    return any(t in AFTER_CUES for t in tokens[i + 1 : i + 1 + AFTER_WINDOW])


def check_claims(text: str) -> Verdict:
    lowered = (text or "").lower()
    hits = [
        m.group(0)
        for rx in HARD_CLAIM_RES
        for m in rx.finditer(lowered)
        if not any(t in NEGATIONS for t in TOKEN_RE.findall(lowered[max(0, m.start() - 24) : m.start()])[-2:])
    ]
    for clause in CLAUSE_SPLIT_RE.split(lowered):
        tokens = TOKEN_RE.findall(clause)
        for i, token in enumerate(tokens):
            if token in FORBIDDEN_WORDS and not _claim_allowed(token, tokens, i):
                hits.append(token)
    for m in OVERCLAIM_RE.finditer(lowered):
        if "peluang" not in lowered[max(0, m.start() - OVERCLAIM_WINDOW) : m.start()]:
            hits.append(m.group(0))
    if hits:
        return Verdict(False, "claim", sorted(set(hits)))
    return Verdict(True)


def validate_text(text: str, allowed: Iterable[float]) -> Verdict:
    if not text or not text.strip():
        return Verdict(False, "empty")
    claims = check_claims(text)
    if not claims.ok:
        return claims
    return check_numbers(text, allowed)
