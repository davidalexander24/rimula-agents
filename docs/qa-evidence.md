# QA evidence — kriteria penerimaan (PRD §17.2)

> Pemilik: Nico (D-09/D-10). Putaran uji: 17 Sep 2026 22:08–22:11 WIB · release `fp-20260917-150636` (demo :8000) + instance dev nico (:8004 untuk AC-09, AC-10, AC-13).
> Uji otomatis: `var/nico/ac/ac_test.py` + `var/nico/ac/run_all.sh` (hasil mentah `var/nico/ac_results.jsonl`, log `var/nico/logs/ac_*.log`). Loop global demo direset di awal dan akhir.

**Ringkasan: 16/16 PASS.**

| ID | P | Skenario | Hasil wajib | Waktu | Penguji | Hasil | Catatan |
|---|---|---|---|---|---|---|---|
| AC-01 | P0 | Notebook restart → start_demo.sh | LLM + demo hidup, health semua true ≤ 4 menit | 22:08 | nico (agent) | **PASS** | stop_demo lalu start_demo: exit 0, health OK dalam 37 dtk (batas 240). Catatan: restart notebook & llama-server tidak disimulasikan (R9, izin David); LLM sudah hidup. |
| AC-02 | P0 | Explore, brief default, n=3, tanpa orchestrator | 3 kandidat valid (100%), prediksi, interval, P_TARGET, gate ≤ 8 dtk | 22:08 | nico (agent) | **PASS** | run explore n=3 tanpa orchestrator 3.9 dtk; total komposisi [100.0, 100.0, 100.0]; gate ['review', 'review', 'review']; P_TARGET [0.95, 0.95, 0.95] |
| AC-03 | P0 | Setujui kandidat review tanpa centang | Ditolak 409, UI menjelaskan | 22:08 | nico (agent) | **PASS** | setujui kandidat review tanpa centang -> HTTP 409 ACK_REQUIRED "Kandidat perlu ditinjau. Centang bahwa peringatan Guardian sudah dibaca."; UI: tombol Simpan keputusan nonaktif sampai kotak peringatan dicentang |
| AC-04 | P0 | Setujui → Uji di Virtual Lab | Hasil + ✓/✗ + batch ke-N; versi model naik ≤ 10 dtk | 22:08 | nico (agent) | **PASS** | uji Virtual Lab HTTP 200 0.2 dtk; batch ke-1; lolos 6/6 per spesifikasi; model -> gp-global-v3 |
| AC-05 | P0 | 3–6 siklus jalankan-uji | Progress tercatat; kandidat berubah; terbaik tidak turun | 22:08 | nico (agent) | **PASS** | 4 siklus tambahan: batch [2, 3, 4, 5]; spesifikasi terbaik [6, 6, 6, 6] (tidak turun); kandidat berbeda tiap siklus: True; versi model ['gp-global-v4', 'gp-global-v5', 'gp-global-v6', 'gp-global-v7'] |
| AC-06 | P0 | Reset loop | Batch 0, model gp-global-v1 | 22:08 | nico (agent) | **PASS** | reset -> batches 0, model aktif gp-global-v1 |
| AC-07 | P0 | Replay: sesi → run → setujui → ungkap | Hasil historis; model sesi naik; tidak ada nilai pool bocor | 22:08 | nico (agent) | **PASS** | sesi rs_0f02d75f82bf: 10 baris awal, 0 hit; kandidat pool tanpa hasil lab sebelum diungkap (bocor=False); ungkap HTTP 200 source=historical 5/6; model sesi gp-session-rs_0f02d75f82bf-v1 -> gp-session-rs_0f02d75f82bf-v2 |
| AC-08 | P0 | Tab Bukti | Angka identik evaluation.json; 3 skenario + penghematan | 22:08 | nico (agent) | **PASS** | GET /evaluation identik dengan artifacts/evaluation.json release (generated_at 2026-09-17T22:04:21+07:00); varian ['v1', 'v2', 'v3']; tab Bukti membaca endpoint ini tanpa transformasi angka |
| AC-09 | P0 | Reload & restart backend | Run, keputusan, hasil lab, versi model tetap | 22:09 | nico (agent) | **PASS** | setelah dev_down/dev_up instance nico: run run_c1f819d77d22 done, keputusan approved, hasil lab lab_29603d3a4593, model aktif gp-global-v6 (sebelum restart gp-global-v6) |
| AC-10 | P0 | LLM_BASE_URL instance ke port mati → run orchestrator | Banner degraded; run done dengan template; tanpa 500 | 22:09 | nico (agent) | **PASS** | instance nico dengan LLM_BASE_URL ke port mati (LLM bersama tidak dimatikan): mode=degraded llm_ready=False (banner Mode terbatas di UI); run orchestrator status=done llm_status=degraded ringkasan=['template', 'template', 'template'] 3.5 dtk; tanpa HTTP 500 |
| AC-11 | P1 | Orchestrator hidup, n=3 | Timeline urut; ≤ 45 dtk; ringkasan tanpa angka asing/kata terlarang | 22:09 | nico (agent) | **PASS** | orchestrator n=3 30.3 dtk, llm_status=ok, 33 event berurutan; sumber ringkasan ['template', 'template', 'template']; kata terlarang: tidak ada |
| AC-12 | P1 | Evidence | Kandidat pass/review punya bukti market; ≥ 1 literatur | 22:08 | nico (agent) | **PASS** | bukti market di semua kandidat pass/review: True; literatur per kandidat [3, 3, 3] (scout_ready=True) |
| AC-13 | P1 | Run now Scout/Designer | Job tercatat & selesai | 22:10 | nico (agent) | **PASS** | Run now scout: job job_e079ec0988ea -> done; Run now designer: job job_fc1a3331c399 -> done |
| AC-14 | P0 | Akses dari laptop anggota lain | BASE/proxy/8000/ memuat UI & API | 22:11 | nico (agent) dari laptop tim (luar VPS) | **PASS** | BASE/proxy/8000/ → HTTP 200 <title>FormulaPilot · Ruang eksperimen</title>; bundle assets/index-*.js 200 (650 KB); /api/v1/health mode=live, semua siap. Uji UI penuh di browser (Chrome) pada release sebelumnya: run, setujui, uji, replay, tab Bukti & Agent. |
| AC-15 | P0 | smoke_test.sh 8000 | Semua PASS | 22:08 | nico (agent) | **PASS** | SMOKE PASS: port 8000, 8/8 langkah, 6.3 dtk |
| AC-16 | P0 | Pemeriksaan kata terlarang | grep kosong (kecuali daftar validator/test) | 22:11 | nico (agent) + tinjauan manual | **PASS** | grep -rniE 'lolos bpom/dijamin/formula terbaik' frontend/src fp backend hanya menemukan daftar larangan: fp/orchestrator/prompts.py:24 (instruksi "Jangan menyatakan…"), fp/orchestrator/validate.py:13 (regex validator), fp/guardian.py:3 (docstring "tidak pernah menyimpulkan"). Termasuk pengecualian PRD; frontend/src bersih. (Pemeriksaan otomatis menandai FAIL karena filter terlalu sempit.) |

## Catatan & risiko terbuka

- **AC-01 sebagian**: restart notebook dan llama-server tidak disimulasikan (mematikan LLM bersama butuh izin David, R9). Yang diukur: `stop_demo.sh` → `start_demo.sh` dengan LLM sudah hidup. Perlu diulang saat latihan M4 bila tim setuju.
- **AC-11**: waktu dan urutan lolos, tetapi **semua ringkasan LLM ditolak** validator karena kata "halal" (konteks peringatan sertifikat Guardian) → template. Dilaporkan ke David (`coordination/requests/nico-2134-ambil-alih-dafa.md`).
- **AC-11/AC-12**: dengan orchestrator ON, LLM menulis kueri literatur sendiri yang sama untuk semua kandidat → literatur identik; tanpa orchestrator kueri `scout.query_for` beragam. Dilaporkan ke David.
- **P_TARGET** kandidat demo 0,95 (maks setelah koreksi noise uji 5%) dan batch pertama umumnya lolos 6/6 di Virtual Lab v1; mode Replay memperlihatkan loop (contoh ungkap 5/6).
- Uji ulang wajib setelah release M3 dan M4 (D-10); tabel ini diperbarui setiap putaran.

## Verifikasi perbaikan orchestrator — 2026-09-18T00:20:12+07:00

- Release aktif: fp-20260917-171521; tiga file perbaikan David identik dengan sumber; cwd proses port 8000 terverifikasi sesuai release.
- Pengambilalihan ops oleh Dafa atas instruksi pengguna; script resmi memakai identitas nico.
- Backend: 179 passed, 1 skipped (68,93 detik). Peringatan deprecation dan convergence tidak menggagalkan tes.
- Smoke API port 8000: 8/8 PASS, 6,3 detik. Run run_e561e146de4f; explore 4,7 detik; uji+retrain 0,3 detik.
- Tepat satu run orchestrator: run_7194d8d083ad, done, llm_status=ok, 32,39 detik, 27 event, 3 kandidat.
- Ringkasan: 3/3 source=llm; tidak ada event summary_rejected.
- Literatur: 3 artikel per kandidat; 9 artikel unik, tidak ada irisan antarkandidat; query_source kandidat 2/3 = query_for_dedup.
- Seluruh flag kesiapan health bernilai true; loop global batches=0, model gp-global-v1 setelah smoke.
- Bukti mentah: var/nico/orchestrator-run_7194d8d083ad.json; ringkasan: var/nico/verification-run_7194d8d083ad.json; smoke: var/nico/logs/smoke-fp-20260917-171521.log.
- Riwayat demo sebelum release tetap berada di ~/work/release/fp-20260917-150636/var/demo/; tidak dimigrasikan ke DB release baru.
- Batas pemeriksaan: ini tes backend, smoke, dan satu run orchestrator, bukan pengulangan seluruh AC/browser. Kandidat blocked masih belum diuji manual.
