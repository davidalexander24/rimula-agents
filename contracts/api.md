# Kontrak API FormulaPilot

**Versi kontrak 1.0 · dibekukan 17 Sep (B-01) · pemilik: David (B)**

Turunan PRD §13.7, §14.3 sampai §14.6. Tipe data resmi ada di `fp/schemas.py`; file ini menjelaskan cara memakainya. Jika file ini dan `fp/schemas.py` berbeda, **`fp/schemas.py` yang berlaku**.

Perubahan kontrak: buat request `coordination/requests/<nama>-<HHMM>-kontrak-<topik>.md` ke David (R2, R3). David mengumumkan di grup **sebelum** menerapkan, menaikkan `CONTRACT_VERSION`, dan memperbarui fixture.

---

## 1. Dasar

| Item | Aturan |
|---|---|
| Base path | `api/v1` relatif terhadap halaman. Browser: `BASE/proxy/<port>/api/v1/...`. Frontend fetch `api/v1/...` **tanpa** `/` di depan |
| Swagger | `BASE/proxy/<port>/docs` |
| Format | JSON UTF-8. Angka memakai titik desimal. Format Indonesia (`1.234,5`) hanya di frontend |
| Waktu | ISO 8601 dengan zona `+07:00`, contoh `2026-09-17T19:30:00+07:00` |
| ID | prefix + 12 hex: `run_`, `cand_`, `rs_`, `lab_`, `job_`, `req_` |
| Header | Setiap respons membawa `X-Request-ID`. Jika request mengirim header ini, nilainya dipakai ulang |
| Frontend statis | Router API dipasang lebih dulu, lalu `frontend/dist` di `/`. Jika `dist` belum ada, `/` mengembalikan HTML "Frontend belum di-build" |

## 2. Envelope

Semua endpoint JSON memakai envelope (`Envelope`, `ErrorEnvelope`):

```json
{"mode": "live", "data": { ... }}
{"mode": "degraded", "error": {"code": "GATE_BLOCKED", "message": "...", "request_id": "req_0a1b2c3d4e5f"}}
```

`mode` = `live` jika model Designer siap **dan** LLM siap; selain itu `degraded`. Mode degraded tetap berfungsi penuh tanpa orchestrator (ringkasan template). Banner frontend membaca `mode`; rinciannya ada di `GET /health`.

Pengecualian: `GET /evaluation/figures/{name}` mengembalikan PNG langsung (error tetap envelope).

## 3. Kode error

| HTTP | `code` | Kapan |
|---|---|---|
| 422 | `VALIDATION_ERROR` | body/query tidak sesuai schema. `message` menyebut field pertama yang salah |
| 422 | `REASON_REQUIRED` | alasan keputusan kurang dari 5 karakter (setelah trim) |
| 404 | `NOT_FOUND` | path tidak dikenal |
| 404 | `BRIEF_NOT_FOUND` · `SESSION_NOT_FOUND` · `RUN_NOT_FOUND` · `CANDIDATE_NOT_FOUND` | ID tidak ada |
| 404 | `EVALUATION_MISSING` · `FIGURE_NOT_FOUND` · `MARKET_NOT_READY` · `AGENT_NOT_FOUND` | artefak/agent belum ada |
| 409 | `RUN_IN_PROGRESS` | sudah ada run `running` pada scope yang sama |
| 409 | `ALREADY_DECIDED` · `GATE_BLOCKED` · `ACK_REQUIRED` | aturan keputusan (§5.3) |
| 409 | `NOT_EXPLORE` · `NOT_APPROVED` · `ALREADY_TESTED` | aturan uji Virtual Lab (§5.4) |
| 409 | `NOT_POOL` · `ALREADY_REVEALED` | aturan ungkap replay (§5.5) |
| 409 | `JOB_RUNNING` | job agent yang sama masih berjalan |
| 503 | `MODEL_NOT_READY` | Designer belum dimuat |
| 503 | `LAB_NOT_READY` | `fp.virtual_lab` / `fp.palette` belum bisa di-import saat `/test` |
| 503 | `DATA_NOT_READY` | `briefs.json` atau `ingredients.csv` belum ada/tidak valid (`/briefs`, `/palette`, `POST /runs`). Otomatis pulih saat file tersedia |
| 500 | `INTERNAL_ERROR` | exception tak terduga; detail hanya di log instance, dicari lewat `request_id` |

Pesan error berbahasa Indonesia dan boleh ditampilkan langsung ke pengguna.

## 4. Endpoint

Kolom **Respons** adalah isi `data`. Nama tipe merujuk `fp/schemas.py`.

| Method & path | P | Request | Respons | Fixture | Error |
|---|---|---|---|---|---|
| `GET /health` | P0 | | `Health` | `health.json` | |
| `GET /briefs` | P0 | | `list[Brief]` | `briefs.json` | |
| `GET /palette` | P0 | | `Palette` | `palette.json` | |
| `GET /progress?scope=global` | P0 | `scope` = `global` atau `session:<id>` | `Progress` | `progress.json` | `SESSION_NOT_FOUND` |
| `POST /progress/reset` | P0 | `ProgressResetRequest` | `Progress` (kosong, model kembali `gp-global-v1`) | | |
| `POST /runs` | P0 | `RunCreate` | `RunCreated`, HTTP **202** | | `BRIEF_NOT_FOUND`, `SESSION_NOT_FOUND`, `MODEL_NOT_READY`, `RUN_IN_PROGRESS` |
| `GET /runs/{run_id}?after_seq=0` | P0 | | `Run`, `events` hanya `seq > after_seq` | `run_done.json` | `RUN_NOT_FOUND` |
| `GET /runs?limit=20` | P1 | | `list[RunListItem]`, terbaru dulu | | |
| `POST /candidates/{id}/decision` | P0 | `DecisionRequest` | `Candidate` | `candidate_*.json` | `CANDIDATE_NOT_FOUND`, `ALREADY_DECIDED`, `REASON_REQUIRED`, `GATE_BLOCKED`, `ACK_REQUIRED` |
| `POST /candidates/{id}/test` | P0 | | `LabTestResponse` | `lab_test.json` | `CANDIDATE_NOT_FOUND`, `NOT_EXPLORE`, `NOT_APPROVED`, `ALREADY_TESTED` |
| `POST /candidates/{id}/manual-result` | P2 | `ManualResultRequest` | `LabTestResponse` (`source=manual`) | | seperti `/test` |
| `POST /replay/sessions` | P0 | `ReplaySessionCreate` | `ReplaySession` (`seed` terisi, `progress` null) | `replay_session.json` | `BRIEF_NOT_FOUND` |
| `GET /replay/sessions/{id}` | P0 | | `ReplaySession` (`progress` terisi) | | `SESSION_NOT_FOUND` |
| `POST /candidates/{id}/reveal` | P0 | | `LabTestResponse` (`source=historical`) | | `CANDIDATE_NOT_FOUND`, `NOT_POOL`, `NOT_APPROVED`, `ALREADY_REVEALED` |
| `GET /evaluation` | P0 | | `EvaluationReport` (isi `artifacts/evaluation.json` apa adanya) | `evaluation_min.json` | `EVALUATION_MISSING` |
| `GET /evaluation/figures/{name}` | P1 | `name` seperti `closed_loop_v1.png` | PNG | | `FIGURE_NOT_FOUND` |
| `GET /models?scope=` | P1 | | `list[ModelVersion]`, terbaru dulu | | |
| `GET /market/summary` | P1 | | ringkasan `ingredient_stats.json` tanpa `examples` | | `MARKET_NOT_READY` |
| `POST /agents/{agent}/run` | P1 | `agent` = `designer` / `scout` / `guardian` | `JobCreated`, HTTP **202** | | `AGENT_NOT_FOUND`, `JOB_RUNNING` |
| `GET /agents/status` | P1 | | `AgentsStatus` | | |

## 5. Perilaku

### 5.1 Run dan polling
1. `POST /runs` langsung mengembalikan 202 `{run_id, status: "running"}`. Pekerjaan berjalan di thread.
2. Frontend polling `GET /runs/{run_id}?after_seq=<seq terakhir>` tiap 1 detik sampai `status` = `done` atau `failed`, lalu menambahkan `events` baru ke timeline.
3. `candidates` selalu dikirim lengkap (bukan inkremental) dan terisi bertahap selama run berjalan. Kartu kandidat boleh muncul sebelum `done`. Selama belum diperiksa Guardian, `gate` berisi issue `PENDING_CHECK` (info) dan `summary.source="unavailable"`, `summary.reason="pending"`; tombol keputusan sebaiknya nonaktif sampai run `done`.
4. `specs` di request menimpa `specs` brief. `n` 1 sampai 5 (default 3). `use_orchestrator` default `false`.
5. `run_mode=replay` wajib `session_id`. Kandidat replay ber-`origin=pool` dengan `source_record_id`; **hasil lab baris pool tidak pernah dikirim sebelum diungkap**.
6. Scope untuk `RUN_IN_PROGRESS`: explore = `global`, replay = `session:<session_id>`.
7. `llm_status`: `not_used` (orchestrator off), `ok`, atau `degraded` (LLM gagal/timeout; run tetap `done` dengan ringkasan template).
8. Run yang masih `running` lebih dari `RUN_TIMEOUT_S` (default 180 dtk) otomatis menjadi `failed` dengan event `system/error` (`detail.reason = "run_timeout"`). UI cukup menampilkan `error`.

### 5.2 Event (`AgentEvent`)
- `seq` naik 1, 2, 3, ... per run.
- `agent`: `orchestrator` · `designer` · `guardian` · `scout` · `lab` · `system`.
- `action`: `run_started`, `run_finished`, `llm_step`, `propose`, `explain`, `check`, `literature`, `market`, `summarize`, `lab_batch`, `retrain`, `policy_enforced`, `policy_override`, `fallback_template`, `summary_rejected_number`, `summary_rejected_claim`, `error`.
- Setiap eksekusi tool menulis `started` lalu `done` atau `failed`. **Pasangan `started`/`done` punya `detail.call` yang sama**, sehingga timeline bisa menggabungkannya. `duration_ms` hanya ada di event `done`/`failed`.
- Event tanpa pasangan (misalnya `llm_step`, `run_started`) langsung berstatus `done`.
- `detail` maksimal 1.000 karakter dan tidak pernah berisi prompt penuh.
- `scout/literature` (`started`): `detail.query`, `detail.query_source` = `llm` (kueri dari LLM), `query_for` (kueri deterministik), atau `query_for_dedup` (kueri LLM sama dengan kandidat lain, diganti kueri kandidat). `done`: `detail.n_results`, `detail.n_reused` (artikel yang juga dipakai kandidat sebelumnya).
- `summary_rejected_number` / `summary_rejected_claim`: `detail.offending` (token yang ditolak) dan `detail.text_preview` (≤ 240 karakter teks LLM yang ditolak).

### 5.3 Keputusan (`POST /candidates/{id}/decision`)
Dicek berurutan:
0. Run kandidat masih `running` → 409 `RUN_IN_PROGRESS` (gate belum final).
1. Sudah ada `decision` → 409 `ALREADY_DECIDED`.
2. `reason` setelah trim kurang dari 5 karakter → 422 `REASON_REQUIRED` (berlaku untuk setuju dan tolak).
3. `decision=approved` dan `gate.status=blocked` → 409 `GATE_BLOCKED`.
4. `decision=approved`, `gate.status=review`, `acknowledged=false` → 409 `ACK_REQUIRED`.

### 5.4 Uji Virtual Lab (`POST /candidates/{id}/test`)
Hanya kandidat `origin=explore` (`NOT_EXPLORE`), `decision=approved` (`NOT_APPROVED`), dan belum punya `lab_result` (`ALREADY_TESTED`). Backend menjalankan `VirtualLab.run_batch` (varian `VIRTUAL_LAB_VARIANT`, seed dari `candidate_id`), menyimpan hasil, retrain model global, lalu mengembalikan kandidat yang sudah berisi `lab_result`, `lab_result` itu sendiri, dan `progress` terbaru. `lab_result.retrained_model_version` = versi model baru.

### 5.5 Replay
- `POST /replay/sessions` memilih 10 baris awal `historical_v1` yang **tidak** memenuhi semua spesifikasi (deterministik per `seed`), lalu melatih `gp-session-<session_id>-v1`. `known` hanya berisi baris yang sudah terbuka (awal + terungkap, urut). `pool_size` = baris yang belum terbuka.
- `POST /runs` dengan `run_mode=replay` wajib `session_id` dan `brief_id` yang sama dengan brief sesi (beda → 422). Designer hanya melihat `record_id` + kolom formula pool.
- `POST /candidates/{id}/reveal` hanya untuk `origin=pool` (`NOT_POOL`), `approved` (`NOT_APPROVED`), dan belum diungkap (`ALREADY_REVEALED`). Hasil historis disimpan dengan `source=historical`, `progress.scope=session:<id>`, lalu model sesi di-retrain.
- Progress sesi terpisah dari progress global.

### 5.5b Agent (`/agents/*`, `/market/summary`)
- `POST /agents/designer/run` → job `designer_retrain` (retrain model global, versi naik). `scout` → `scout_reindex` (muat ulang indeks Scout & data market dari artefak). `guardian` → `guardian_recheck` (periksa ulang kandidat yang belum diputuskan pada run explore terakhir; gate di run itu bisa berubah).
- Balasan 202 `{job_id}`; hasil dibaca dari `GET /agents/status` → `<agent>.last_job` (`status` `queued` → `running` → `done`/`failed`, `detail` berisi hasil atau `error`). Polling tiap 1 detik cukup.
- `scheduler.ready=false` sampai B-13 (P2).
- `GET /market/summary` = isi `ingredient_stats.json` tanpa `examples` (`n_products`, `n_by_segment`, `n_indonesia`, `prevalence`, `pair_support`, ...).

### 5.6 Progress
| Field | Aturan |
|---|---|
| `batches` | jumlah hasil lab aktif (`archived=0`) pada scope |
| `hit_at_batch` | `batch_index` pertama dengan `specs_met.ALL=true`, atau `null` |
| `best_specs_met` | jumlah spesifikasi terpenuhi terbanyak (dari 6 kunci, tanpa `ALL`) |
| `total_specs` | 6 |
| `history` | `BatchRecord` urut `batch_index` |

`POST /progress/reset` menandai hasil lab global `archived=1` dan mengaktifkan kembali `gp-global-v1`. Riwayat run dan keputusan tidak dihapus.

### 5.7 Versi model
`gp-global-v1` (dasar, read-only dari `artifacts/models/`), `gp-global-v2`, `gp-global-v3`, ... setelah tiap uji, dan `gp-session-<session_id>-v<N>` untuk replay. Model hasil retrain disimpan di `$FP_RUNTIME_DIR/models/`. Nomor versi tidak pernah dipakai ulang: setelah reset (v1 aktif lagi), retrain berikutnya melanjutkan dari nomor tertinggi (mis. v4). Tampilkan versi apa adanya.

### 5.8 Bukti market di kartu kandidat
Kombinasi lengkap bahan kandidat hampir selalu 0 produk (temuan Nico 17:47). `evidence[type=market].detail` juga berisi `weakest_pair` (mis. `CCT|NIACINAMIDE`) dan `min_pair_support` (jumlah produk pasangan terlemah); tampilkan keduanya di kartu.

## 6. Kunci dan urutan tetap

| Nama (di `fp/schemas.py`) | Isi |
|---|---|
| `FORMULA_FIELDS` | `GLYCERIN, NIACINAMIDE, CETEARYL_ALCOHOL, EMULSIFIER, CCT, DIMETHICONE, XANTHAN, CARBOMER, NAOH, PHENOXYETHANOL, AQUA, RPM, HMIN, TEMP` |
| `SPEC_KEYS` | `NIACINAMIDE_MIN_PCT, VISCOSITY_CP, PH, D50_UM_MAX, STABLE, COST_IDR_PER_KG_MAX` |
| `SPECS_MET_KEYS` | `SPEC_KEYS` + `ALL` |
| `P_SPECS_KEYS` | `P_VISC, P_PH, P_D50, P_STABLE, DET_OK` |
| `LAB_OUTPUT_KEYS` | `VISCOSITY_CP, PH, D50_UM, STABILITY_INDEX, STABLE, COST_IDR_PER_KG` (`STABLE` bernilai 0/1) |

Pasangan rentang (`VISCOSITY_CP`, `PH`, `*_CI95`) dikirim sebagai array JSON `[min, max]`.

## 7. Fixture (`contracts/fixtures/`)

Isi fixture = `data` respons (tanpa envelope), kecuali `error_gate_blocked.json` yang berisi envelope error lengkap. Semua fixture divalidasi `backend/tests/test_api_contracts.py`.

| File | Tipe | Catatan |
|---|---|---|
| `health.json` | `Health` | |
| `briefs.json` | `list[Brief]` | sama dengan §8.1.5 PRD |
| `palette.json` | `Palette` | sama dengan §8.1.1 PRD |
| `run_done.json` | `Run` | orchestrator on, 3 kandidat `review` / `pass` / `blocked`, 24 event |
| `candidate_review.json`, `candidate_pass.json`, `candidate_blocked.json` | `Candidate` | sama dengan isi `run_done.json` |
| `progress.json` | `Progress` | 2 batch, belum hit |
| `lab_test.json` | `LabTestResponse` | kandidat #1 disetujui dan diuji, hit di batch 3 |
| `replay_session.json` | `ReplaySession` | 10 baris awal tanpa hit |
| `evaluation_min.json` | `EvaluationReport` | `quick: true`, `notes: ["FIXTURE", ...]`; hanya dipakai frontend jika `GET /evaluation` 404, dengan banner "DATA CONTOH" |
| `error_gate_blocked.json` | `ErrorEnvelope` | contoh error 409 |

Komposisi fixture total 100% dan output-nya dihitung dari persamaan Virtual Lab v1 (§8.1.2). Prediksi, bukti pasar, dan literatur adalah **contoh** bertanda `[FIXTURE]`; jangan dipakai sebagai angka atau sitasi di UI final maupun deck (R11).
