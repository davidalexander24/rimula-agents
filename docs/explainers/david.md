# Explainer: David (B), kontrak, backend, orchestrator, LLM (Rimula Agents)

Nama produk: **Rimula Agents** (nama paket kode tetap `fp/`, `formulapilot/`). Bagian saya adalah jalur dari tombol "Jalankan" di UI sampai kartu kandidat, hasil uji Virtual Lab, dan model yang belajar. Model, aturan, dan data dibuat anggota lain; backend yang merangkainya dan menjaga agar LLM tidak pernah menjadi sumber angka.

## Apa yang saya buat

| Area | File |
|---|---|
| Kontrak data | `fp/schemas.py`, `contracts/api.md`, `contracts/fixtures/*.json` |
| Fondasi bersama | `fp/config.py` (path, env per instance), `fp/io_utils.py` (tulis atomik) |
| Orchestrator LLM | `fp/orchestrator/` : `loop.py`, `tools.py`, `prompts.py`, `validate.py`, `templates.py`, `client.py` |
| Backend | `backend/app/`: `factory.py`, `state.py`, `db.py`, `repo.py`, `jobs.py`, `services/` (runs, pipeline, candidates, lab, training, replay), `api/` (health, briefs, runs, candidates, replay, progress, evaluation, agents) |
| Test | `backend/tests/conftest.py`, `test_api.py`, `test_api_contracts.py`, `test_orchestrator.py` |
| LLM | llama-server Qwen3-30B-A3B di port 8080 |

## Cara kerja dalam 5 kalimat

1. Formulator memilih brief, lalu `POST /runs` langsung dibalas dan pekerjaan berjalan di thread, sementara UI membaca kemajuan lewat polling event per detik.
2. Orchestrator (Qwen3 lokal) memanggil tool: Designer mengusulkan kandidat, Guardian memeriksa aturan, Scout mencari bukti pasar dan literatur; LLM hanya merujuk `candidate_id` dan tidak pernah mengetik ulang komposisi.
3. Setelah LLM selesai, backend menjalankan policy enforcement: setiap langkah yang terlewat dijalankan ulang secara deterministik, lalu setiap ringkasan LLM divalidasi angka dan klaimnya.
4. Kandidat yang disetujui diuji di Virtual Lab (satu-satunya jalur ke "hasil lab"), hasilnya disimpan sebagai batch, dan model Designer dilatih ulang sehingga versi naik dan usulan berikutnya berubah.
5. Mode replay memakai data historis yang disembunyikan: Designer hanya melihat kolom formula, dan nilai hasil baru dibuka saat formulator menekan "Ungkap".

## Alur satu run

```
UI ──POST /runs──► runs.create_run ──202──► UI polling GET /runs/{id}?after_seq=N
                        │
                        ▼ thread
              LLM siap dan orchestrator ON?
               │ ya                           │ tidak
               ▼                              │
     loop LLM (≤10 langkah, ≤75 dtk)          │
     tool: designer_propose ─► Designer       │
           guardian_check  ─► Guardian        │
           scout_market    ─► Market (OBF)    │
           scout_literature─► Scout (Europe PMC)
               │                              │
               ▼                              ▼
         policy enforcement: jalankan langkah yang terlewat
               │
               ▼
         validasi ringkasan (angka dari hasil tool, tanpa klaim terlarang)
               │ lolos → sumber "llm"    │ gagal → template, sumber "template"
               ▼
         run done ──► kartu kandidat ──► keputusan ──► uji Virtual Lab ──► retrain ──► versi model naik
```

## Anti-halusinasi

- **Angka:** semua angka di ringkasan LLM harus cocok dengan nilai hasil tool untuk kandidat itu (formula, prediksi dan intervalnya, pesan Guardian, bukti, spesifikasi brief), dengan pembulatan ke presisi yang ditulis dan format Indonesia maupun Inggris. Satu angka asing, ringkasan ditolak dan diganti template.
- **Klaim:** kata "halal", "aman", "BPOM", "dijamin", "terbaik", "pasti" ditolak sebagai klaim, begitu pula "memenuhi seluruh spesifikasi" tanpa kata "peluang" (prediksi bukan hasil uji).
- **Struktur:** `n` kandidat dipaksa sama dengan permintaan pengguna, `designer_propose` hanya sekali per run, argumen tool divalidasi, dan `candidate_id` palsu dikembalikan ke LLM sebagai error.
- **Jejak:** setiap penolakan tercatat sebagai event (`summary_rejected_number`, `summary_rejected_claim`, `policy_enforced`, `fallback_template`) dan tampil di timeline.

## Mode degraded

Jika llama-server mati, timeout, atau membalas JSON tidak valid, run tetap selesai: semua langkah dijalankan deterministik, ringkasan memakai template, `llm_status=degraded`, dan banner UI berubah kuning. Tidak ada 500. Mode ini diuji otomatis (LLM diarahkan ke port mati) dan dengan timeout buatan.

## Angka terukur (VPS, 17 Sep, lewat proxy Jupyter)

| Hal | Hasil | Target PRD |
|---|---|---|
| Run explore n=3 tanpa orchestrator | 5,0 dtk | ≤ 8 dtk (AC-02) |
| Run dengan orchestrator Qwen3 lokal, n=3 | 21,7 sampai 30,6 dtk; `llm_status=ok`; 0 ringkasan ditolak setelah perbaikan prompt | ≤ 45 dtk (AC-11) |
| Uji Virtual Lab + retrain warm start | 0,3 dtk | ≤ 10 dtk (AC-04) |
| Run replay + ungkap | 1,5 dtk | - |
| Smoke test live 17 langkah | 17/17 PASS | - |

## Pertanyaan juri yang mungkin

**"Bagaimana kalau LLM-nya berhalusinasi angka?"**
LLM tidak pernah menjadi sumber angka. Angka datang dari model Gaussian Process dan Virtual Lab lewat tool, lalu setiap angka di ringkasan dicocokkan ulang dengan hasil tool; satu angka asing membuat ringkasan diganti template yang dihitung langsung dari data. Semua penolakan terlihat di timeline agent.

**"Kenapa tidak pakai ChatGPT atau API luar saja?"**
Data formulasi adalah rahasia dagang. Qwen3-30B-A3B berjalan lokal di GPU 12 GB dengan llama.cpp, sehingga tidak ada data formula yang keluar, dan pola ini bisa dipasang on-premise saat pilot.

**"Apa yang terjadi kalau servernya bermasalah saat demo?"**
Sistem punya mode degraded: tanpa LLM seluruh alur tetap jalan dengan ringkasan template. Run yang macet otomatis ditandai gagal setelah batas waktu, dan model hasil retrain serta hasil lab tersimpan per instance sehingga restart tidak menghapus riwayat.

**"Bagaimana Anda mencegah data historis bocor di mode replay?"**
Designer hanya menerima `record_id` dan kolom formula. Nilai viskositas, pH, droplet, dan stabilitas dibaca dari file hanya saat kandidat diungkap, dan ada test yang memastikan nilai tersebut tidak muncul di respons run sebelum diungkap.

## Batasan

- Validasi anti-halusinasi bersifat leksikal: angka dan kata dicek, makna kalimat tidak. Kalimat yang angkanya benar tetapi penafsirannya berlebihan tetap mungkin lolos; karena itu label sumber ("Ringkasan orchestrator" atau "Ringkasan otomatis") selalu ditampilkan.
- Orchestrator bergantung pada kemampuan tool calling Qwen3; urutan langkah dijamin oleh policy enforcement, bukan oleh LLM.
- Satu proses backend per instance dengan SQLite di NFS; cukup untuk demo dan pilot kecil, bukan untuk banyak pengguna bersamaan.
- Semua hasil "lab" di mode explore berasal dari Virtual Lab simulasi, bukan lab nyata.
