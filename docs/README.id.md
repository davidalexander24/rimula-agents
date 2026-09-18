# FormulaPilot

**Co-pilot eksperimen formulasi skincare** — usulan formula berikutnya dengan peluang lolos spesifikasi, pemeriksaan batas & catatan regulasi, bukti literatur dan produk nyata, lalu belajar dari setiap hasil uji. Keputusan tetap di tangan formulator.

Tim **Codingbang** (Nico, Dafa, David, Marshal) · Hackathon use case Paragon "AI untuk Riset & Prediksi Formulasi" · 17–18 September 2026.

> **Pernyataan kejujuran**
> - Virtual Lab adalah **simulator buatan tim** dengan persamaan terbuka (`docs/virtual-lab-model-card.md`). Arah hubungan antarvariabel mengacu literatur, tetapi angkanya bukan hasil lab nyata.
> - Kemampuan metode pada **data eksperimen nyata** ditunjukkan terpisah pada dataset liposom publik (non-skincare), hanya untuk validasi.
> - Semua estimasi biaya dan waktu adalah asumsi simulasi.

## Cara kerja

```
Brief & spesifikasi ──► Designer (4 Gaussian Process + Bayesian optimization)
                          │  usulkan n formula, rentang 95%, peluang tiap spesifikasi
                          ▼
                        Guardian (aturan palet, klaim, anggaran, regulasi & catatan sumber halal — asumsi tim)
                          ▼
                        Scout ─ literatur Europe PMC (bge-m3) ─ produk nyata Open Beauty Facts
                          ▼
Formulator setuju/tolak ──► Uji di Virtual Lab (explore) / ungkap data historis (replay)
                          ▼
                        Designer dilatih ulang (±1 dtk) ──► batch berikutnya
```

Orchestrator opsional: **Qwen3-30B-A3B lokal** (llama.cpp) memanggil agent lewat tool calling dan menulis ringkasan; ringkasan dengan angka asing atau klaim terlarang ditolak dan diganti template. Tanpa API LLM eksternal — semua berjalan on-premise.

| Tab UI | Isi |
|---|---|
| **Eksperimen** | Mode Explore/Replay, timeline agent, kartu kandidat (formula INCI, prediksi + rentang 95%, gate Guardian, bukti, keputusan, hasil uji), loop belajar |
| **Bukti** | Estimasi penghematan (simulasi), closed-loop AI vs acak vs heuristik pada 3 varian simulator, replay data historis, validasi liposom nyata, akurasi CV |
| **Agent & Riset** | Status agent + Run now, statistik Open Beauty Facts, riwayat versi model |

Semua angka di tab Bukti dan deck berasal dari `artifacts/evaluation.json` (`python -m fp.evaluate --all`).

## Struktur

```
fp/            designer, registry, strategies, evaluate, virtual_lab, palette, datagen,
               guardian, market, scout, validation_liposome, orchestrator/, schemas, config, io_utils
backend/       FastAPI (API + menyajikan frontend/dist), SQLite per instance, tests/
frontend/      React + TypeScript + Vite + Tailwind + TanStack Query + Recharts
data/          assumptions/, virtual_lab/, market/, validation/liposome/
artifacts/     models/, evaluation.json, figures/, market/, scout/
scripts/       env, setup_env, fetch_data, generate_data, train, evaluate, build_scout,
               build_frontend, dev_up/down, release, start/stop_demo, smoke_test, status, heavy, snapshot
docs/          PRD, model card, sumber & lisensi, QA evidence, explainer
```

## Menjalankan (Linux, Python 3.13, GPU opsional)

```bash
# 1. Lingkungan (venv ~/work/venvs/fp, Node 22 di ~/work/node-env)
bash scripts/setup_env.sh
FP_MEMBER=nico source scripts/env.sh          # port & folder runtime per anggota

# 2. Data & artefak
bash scripts/heavy.sh bash scripts/fetch_data.sh      # Open Beauty Facts + dataset liposom (Zenodo)
bash scripts/heavy.sh bash scripts/generate_data.sh   # data historis Virtual Lab v1/v2/v3
bash scripts/heavy.sh bash scripts/train.sh           # model dasar gp-global-v1
bash scripts/heavy.sh bash scripts/build_scout.sh     # statistik pasar + indeks literatur
bash scripts/heavy.sh bash scripts/evaluate.sh        # evaluation.json + figur (±2–3 menit)
bash scripts/heavy.sh bash scripts/build_frontend.sh  # frontend/dist

# 3. LLM lokal (opsional; tanpa LLM aplikasi berjalan mode degraded dengan ringkasan template)
bash ~/work/start_llm.sh                       # llama-server Qwen3-30B-A3B di :8080

# 4. Jalankan
bash scripts/dev_up.sh nico                    # instance dev
bash scripts/release.sh && bash scripts/start_demo.sh   # release beku di :8000
bash scripts/smoke_test.sh 8000                # 8 langkah API
```

Konfigurasi di `.env` (lihat `.env.example`): `LLM_BASE_URL`, `LLM_MODEL`, `VIRTUAL_LAB_VARIANT`, `SCOUT_QUERY_DEVICE`, dll.

## Pengujian

```bash
bash scripts/heavy.sh pytest -q backend/tests   # unit & API test
bash scripts/smoke_test.sh 8000                 # smoke test demo
```
Hasil kriteria penerimaan AC-01..AC-16: `docs/qa-evidence.md`.

## Sumber & lisensi

Kode tim: **Apache-2.0** (`LICENSE`). Data dan model pihak ketiga memiliki lisensinya sendiri — Open Beauty Facts (ODbL), dataset liposom Zenodo 10.5281/zenodo.17867478 (CC BY 4.0), Europe PMC (lisensi per artikel), Qwen3 (Apache-2.0), bge-m3 (MIT), llama.cpp (MIT). Rincian: `docs/sources-and-licenses.md`.
