# Sumber data, model, dan lisensi — FormulaPilot

> Pemilik: Nico (D-09). Lisensi dicek langsung ke sumber resmi pada 17 September 2026 (API Zenodo, Hugging Face, GitHub, paket terpasang).
> Kode FormulaPilot sendiri berlisensi **Apache-2.0** (lihat `LICENSE`). Lisensi itu **hanya untuk kode tim**, tidak untuk data dan model pihak ketiga di bawah.

## 1. Data

| Sumber | Dipakai untuk | Lisensi | Atribusi / catatan |
|---|---|---|---|
| **Virtual Lab** (simulator buatan tim, `fp/virtual_lab.py`) dan data historis turunannya (`data/virtual_lab/historical_v*.csv`) | Melatih & menguji Designer; skenario A dan B | Bagian dari kode tim (Apache-2.0) | **Data sintetis.** Persamaan terbuka di `docs/virtual-lab-model-card.md`; angka bukan hasil lab nyata. |
| **Open Beauty Facts** — dump `en.openbeautyfacts.org.products.csv.gz` (diunduh 17 Sep 2026, SHA-256 di `data/market/SHA256SUMS`) | Bukti pasar: kelaziman bahan & kombinasi (`fp/market.py`), aturan Guardian `UNCOMMON_COMBINATION` | Basis data: **Open Database License (ODbL) 1.0**; isi basis data: Database Contents License (DbCL) 1.0 | "Data produk dari Open Beauty Facts (openbeautyfacts.org), ODbL." Turunan (`obf_skincare_clean.parquet`, `ingredient_stats.json`) juga berada di bawah ODbL (share-alike). Nama merek hanya ditampilkan sebagai contoh produk publik dengan atribusi. Gambar produk tidak dipakai. |
| **Smart Microfluidics: a curated dataset of microfluidic liposome formulations with cross-laboratory validation for machine-learning applications** — Lavagna, L.; Buttitta, G. (2025), Zenodo, DOI [10.5281/zenodo.17867478](https://doi.org/10.5281/zenodo.17867478), file `microfluidics_dataset.zip` | Validasi metode pada data eksperimen nyata (skenario C, `fp/validation_liposome.py`). **Tidak** dipakai melatih model skincare. | **CC BY 4.0** (metadata Zenodo) | Wajib atribusi penulis & DOI. ⚠️ PRD §22 menulis "CC BY-NC"; metadata resmi Zenodo = CC BY 4.0 — dokumen ini mengikuti Zenodo. |
| **Europe PMC** — REST API `webservices/rest/search`, subset `OPEN_ACCESS:y` (8 kueri, 610 abstrak, 17 Sep 2026) | Bukti literatur Scout (`fp/scout.py`): judul, tahun, jurnal, cuplikan abstrak ≤ 300 karakter, tautan | Metadata & abstrak dari Europe PMC; **setiap artikel memiliki lisensinya sendiri** (subset open access, umumnya CC BY / CC BY-NC) | UI selalu menampilkan judul, jurnal, tahun, PMCID, dan tautan ke artikel asli. Teks lengkap tidak disalin. Skor = kemiripan semantik, bukan penilaian kualitas bukti. |
| **Asumsi tim** — `data/assumptions/{ingredients.csv, briefs.json, business.csv, regulatory.csv, inci_synonyms.csv}` | Palet bahan, harga, brief, biaya/batch, batas regulasi & catatan sumber halal | Kode tim (Apache-2.0) | **Semua angka asumsi.** `regulatory.csv` bertanda `verified=false`; sumber yang perlu dicek dicantumkan per baris (Peraturan BPOM No. 17 Tahun 2022, BPJPH/LPPOM). Guardian tidak pernah menyimpulkan "halal", "aman", atau "lolos BPOM". |

## 2. Model

| Model | Dipakai untuk | Lisensi | Sumber |
|---|---|---|---|
| **Qwen3-30B-A3B-Instruct-2507**, kuantisasi GGUF Q4_K_M | Orchestrator LLM lokal (tool calling, ringkasan) — dijalankan on-premise lewat llama.cpp, tanpa API eksternal | **Apache-2.0** | huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507 |
| **BAAI/bge-m3** | Embedding pencarian literatur Scout | **MIT** | huggingface.co/BAAI/bge-m3 |
| **Designer** — 4 Gaussian Process (scikit-learn) dilatih tim | Prediksi viskositas, pH, droplet, stabilitas + peluang spesifikasi | Kode & bobot model tim (Apache-2.0); dilatih dari data sintetis Virtual Lab | `artifacts/models/gp-global-v1.*` |

## 3. Perangkat lunak utama

| Komponen | Versi terpasang | Lisensi |
|---|---|---|
| llama.cpp (ggml-org) | commit 79bfc1d | MIT |
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.53.0 | BSD-3-Clause |
| Pydantic | 2.13.5 | MIT |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| NumPy · pandas · SciPy | 2.5.3 · 3.0.5 · 1.18.1 | BSD-3-Clause |
| PyTorch | 2.14.0 | BSD-3-Clause |
| sentence-transformers | 6.0.1 | Apache-2.0 |
| openai (klien Python, hanya ke llama-server lokal) | 3.14.1 | Apache-2.0 |
| APScheduler | 3.11.3 | MIT |
| pyarrow | 25.0.1 | Apache-2.0 |
| matplotlib | 3.11.2 | Matplotlib License (berbasis PSF) |
| requests | 2.34.2 | Apache-2.0 |
| React · TanStack Query · Recharts · Vite · Tailwind CSS | 18.3.1 · 5.103.1 · 3.10.1 · 6.4.3 · 3.4.19 | MIT |
| lucide-react | 0.468.0 | ISC |

Daftar lengkap versi Python: `requirements.lock`; frontend: `frontend/package-lock.json`.

## 4. Yang TIDAK disertakan dalam paket kode

- Dump mentah Open Beauty Facts (`data/market/obf_raw.csv.gz`) dan zip dataset liposom — unduh ulang dengan `bash scripts/heavy.sh bash scripts/fetch_data.sh`.
- Bobot LLM (±18,6 GB) dan cache bge-m3 — unduh dari Hugging Face.
- `.env`, `var/`, token, materi panitia atau Paragon.

## 5. Pernyataan kejujuran (§1.6)

- Virtual Lab adalah **simulator buatan tim** dengan persamaan terbuka. Arah hubungan antarvariabel mengacu literatur, tetapi angkanya bukan hasil lab nyata.
- Kemampuan metode pada **data eksperimen nyata** ditunjukkan terpisah pada dataset liposom publik (non-skincare), hanya untuk validasi.
- Semua estimasi biaya dan waktu adalah asumsi simulasi.
