# AGENTS.md — FormulaPilot

> Disalin dari `docs/PRD.md` (§0.1, §0.2, §5.2, §6.4–6.6, §6.8) oleh Nico (tugas D-01).
> Jika ada perbedaan, **`docs/PRD.md` yang berlaku**. File ini milik Nico — jangan diedit (R24).
> `CLAUDE.md` berisi hal yang sama.

## Mulai di sini (wajib untuk setiap sesi agent)
1. Jalankan `echo $FP_MEMBER`. Harus berisi nama anggota yang menjalankanmu (`marshal` / `david` / `dafa` / `nico`).
   Jika kosong atau salah: **berhenti** dan minta user menjalankan `FP_MEMBER=<nama> source ~/work/formulapilot/scripts/env.sh`.
2. Baca `docs/PRD.md` §0, §1, §2, §5, §6, dan semua bagian yang dirujuk tugasmu di §18.
3. Baca `coordination/status/*.md` dan permintaan di `coordination/requests/` yang ditujukan kepadamu.
   Ringkasan cepat: `bash scripts/board.sh`.
4. Kerjakan tugas berikutnya di `coordination/status/<nama>.md` yang belum `DONE`, satu per satu.
5. Setelah selesai: jalankan verifikasi tugas, update `coordination/status/<nama>.md`, catat keputusan di `coordination/decisions/<nama>.md`.

## Perintah umum
```bash
FP_MEMBER=<nama> source ~/work/formulapilot/scripts/env.sh   # muat env (port, runtime, cache, thread)
python -m compileall -q fp backend                             # R4: semua modul harus bisa di-compile
pytest -q backend/tests/test_<modulmu>.py                      # test milikmu (satu file boleh langsung)
bash scripts/heavy.sh pytest -q backend/tests                  # seluruh test WAJIB lewat antrean (R18)
bash scripts/heavy.sh <perintah berat>                         # training/evaluasi/build/unduh data
bash scripts/snapshot.sh "<alasan>"                            # sebelum perubahan besar (R14)
bash scripts/board.sh                                          # status semua anggota + request terbuka
bash scripts/dev_up.sh <nama> / dev_down.sh <nama>             # backend dev di port milikmu (setelah D-03)
```

### 0.1 Alur kerja setiap anggota
1. Buka JupyterLab → **terminal milikmu sendiri** (satu terminal per anggota).
2. Muat env dengan identitasmu: `FP_MEMBER=<nama> source ~/work/formulapilot/scripts/env.sh` (`<nama>` = `marshal` / `david` / `dafa` / `nico`). Sebelum D-01 selesai, lihat §0.4.
3. Jalankan AI agent (Claude Code, Codex, dll.) dari folder `~/work/formulapilot` **di terminal itu**. Env sudah mengarahkan config agent ke folder milikmu (§6.9), jadi login dengan akun masing-masing.
4. Beri agent **prompt pembuka** §0.3.
5. Agent mengerjakan tugas milikmu di §18 **berurutan**, lalu menjalankan perintah verifikasi.
6. Setelah tugas lulus, agent memperbarui **file status milikmu** `coordination/status/<nama>.md`.


### 0.2 Aturan wajib untuk SEMUA AI agent
Aturan ini juga disalin ke `~/work/formulapilot/AGENTS.md` dan `CLAUDE.md` (tugas D-01).

| # | Aturan |
|---|---|
| R1 | **Hanya menulis file yang dimiliki anggota yang menjalankanmu** (tabel §5.2). Boleh membaca semua file. **File baru hanya boleh dibuat di dalam folder/pola milikmu.** |
| R2 | Butuh perubahan di file milik orang lain, atau butuh helper bersama → buat file permintaan `coordination/requests/<nama>-<HHMM>-<topik>.md` (§6.6), jangan edit sendiri. |
| R3 | Kontrak data (`fp/schemas.py`, `contracts/api.md`) hanya diubah pemiliknya (David) setelah ada permintaan. |
| R4 | Setiap modul Python **harus selalu bisa di-import**. Setelah mengedit, jalankan `python -m compileall -q fp backend` dan test milikmu. Jangan meninggalkan file setengah jadi. |
| R5 | Tulis file secara utuh (bukan edit bertahap yang meninggalkan sintaks rusak di tengah). |
| R6 | **Semua file di dalam `~/work`.** Jangan menulis ke `/tmp`, `~/.local`, atau folder home lain kecuali cache yang sudah diatur `env.sh`. |
| R7 | Server hanya dinyalakan/dimatikan lewat `bash scripts/dev_up.sh <nama>` / `dev_down.sh <nama>` (port milikmu, §6.4). **Dilarang** menjalankan `uvicorn`/`vite` langsung, memakai port 8000 atau 8080, `pkill`, `killall`, atau `kill` pada PID yang bukan dari file PID milikmu. |
| R8 | Jangan menjalankan `rm -rf` di luar folder milikmu. Jangan menghapus `data/`, `artifacts/`, `var/` milik orang lain. |
| R9 | Jangan memasang ulang, mengganti model, atau me-restart llama-server (port 8080) tanpa izin David. |
| R10 | Jangan memakai API LLM eksternal di dalam kode produk. LLM produk hanya `http://localhost:8080/v1`. |
| R11 | Jangan mengarang angka hasil model, dataset, atau sitasi. Angka di UI/deck dibaca dari `artifacts/*.json`. |
| R12 | Jangan menulis klaim "halal", "aman", "lolos BPOM", "dijamin", "formula terbaik" di kode, UI, atau dokumen. |
| R13 | Jangan menyimpan token Jupyter atau kredensial apa pun di file proyek. |
| R14 | Sebelum mengubah besar-besaran file milikmu yang sudah berfungsi, jalankan `bash scripts/snapshot.sh "<alasan>"`. |
| R15 | Ikuti nama, path, field, dan endpoint persis seperti PRD. Jika PRD ambigu, pilih opsi paling sederhana, catat di `coordination/decisions/<nama>.md`, dan lanjutkan. |
| R16 | Tanda ⚠️ berarti wajib dicek atau diukur; hasilnya dicatat di `coordination/decisions/<nama>.md`. |
| R17 | **Dilarang `pip install`, `pip uninstall`, `mamba/conda install`** di venv/env bersama. Butuh paket → buat permintaan ke Nico (R2). Pengecualian: Dafa boleh `npm install`/`npm ci` **hanya** di `frontend/`. |
| R18 | **Batas CPU:** jangan mengubah `OMP_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`MKL_NUM_THREADS` dari `env.sh`; jangan memakai `n_jobs=-1`. Proses berat (lebih dari ±2 menit CPU, training penuh, evaluasi, build indeks, `npm run build`) **wajib** lewat `bash scripts/heavy.sh <perintah>` (antrean global, §6.8). |
| R19 | **Penulisan atomik:** file data/artefak/JSON/CSV/model ditulis ke file sementara di folder yang sama lalu di-rename (pakai `fp/io_utils.py`). Jangan pernah menulis langsung ke file yang mungkin sedang dibaca orang lain. |
| R20 | **Artefak runtime per instance:** kode backend yang menyimpan model hasil retrain, DB, log, atau cache **wajib** memakai `FP_RUNTIME_DIR` (`var/<instance>/`). Jangan menulis ke `artifacts/` saat aplikasi berjalan. |
| R21 | File status & keputusan: **hanya** `coordination/status/<nama>.md` dan `coordination/decisions/<nama>.md` milikmu. Jangan mengedit file koordinasi anggota lain; permintaan selalu file baru. |
| R22 | Test hanya memakai path sementara di `var/test/<nama>/` (buat dan hapus sendiri). Jangan memakai DB, model, atau port instance mana pun. |
| R23 | Sebelum memakai modul milik orang lain, baca statusnya di `coordination/status/<pemilik>.md`. Jika modul masih stub, pakai stub-nya; jangan menulis implementasi pengganti di file milikmu. |
| R24 | Jangan mengubah `scripts/env.sh`, `AGENTS.md`, `CLAUDE.md`, atau `docs/PRD.md` (milik Nico). Temuan kesalahan PRD → permintaan ke Nico. |
| R25 | Jangan membaca, menyalin, atau mencetak isi folder config agent (`~/work/.agents/`) atau kredensial anggota lain. |
| R26 | Jangan menjalankan `scripts/release.sh`, `start_demo.sh`, `stop_demo.sh` (khusus Nico) atau `scripts/evaluate.sh --all` (khusus Marshal). |


### 5.2 Tabel kepemilikan (acuan aturan R1)
| Anggota | Kode | Boleh menulis |
|---|---|---|
| **Marshal** | A | `fp/palette.py`, `fp/virtual_lab.py`, `fp/datagen.py`, `fp/designer.py`, `fp/registry.py`, `fp/strategies.py`, `fp/evaluate.py`, `fp/validation_liposome.py`, `data/virtual_lab/**`, `data/validation/**`, `data/assumptions/{ingredients.csv,briefs.json,business.csv}`, `artifacts/models/**`, `artifacts/evaluation.json`, `artifacts/figures/**`, `scripts/{generate_data,train,evaluate}.sh`, `backend/tests/test_{palette,virtual_lab,designer,evaluate}.py`, `docs/virtual-lab-model-card.md`, `docs/explainers/marshal.md` |
| **David** | B | `fp/__init__.py`, `fp/config.py`, `fp/io_utils.py`, `fp/schemas.py`, `fp/orchestrator/**`, `backend/**` kecuali test milik A/D, `backend/tests/{conftest,test_api,test_orchestrator}.py`, `contracts/**`, `.env`, `.env.example`, `docs/explainers/david.md`; mengelola llama-server |
| **Dafa** | C | `frontend/**` (termasuk `package.json`, lockfile, `node_modules`, `dist`), `scripts/build_frontend.sh`, `docs/explainers/dafa.md` |
| **Nico** | D | `AGENTS.md`, `CLAUDE.md`, `README.md`, `LICENSE`, `requirements*.txt`, `coordination/README.md`, `scripts/**` kecuali milik A/C, `fp/guardian.py`, `fp/market.py`, `fp/scout.py`, `data/market/**`, `data/assumptions/{regulatory.csv,inci_synonyms.csv}`, `artifacts/market/**`, `artifacts/scout/**`, `backend/tests/test_{guardian,market,scout}.py`, `docs/**` kecuali milik A/B/C, `var/locks/`, `~/work/{node-env,venvs,snapshots,release}`, pembuatan folder kosong `~/work/.agents/*` |
| Semua | — | `coordination/status/<nama>.md`, `coordination/decisions/<nama>.md`, `coordination/requests/<nama>-*.md` (buat baru), bagian "Jawaban" pada request yang ditujukan kepadanya, `var/<nama>/**`, `var/test/<nama>/**`, `~/work/.agents/<nama>/**` |

**Aturan file baru:** file baru hanya boleh dibuat di folder atau pola nama milikmu. Contoh: helper khusus Designer ditaruh di dalam `fp/designer.py` atau file baru `fp/designer_*.py` (milik Marshal); helper Guardian di `fp/guardian_*.py` (Nico); modul orchestrator di `fp/orchestrator/` (David); helper bersama untuk semua orang **hanya** lewat permintaan ke David (`fp/io_utils.py` atau file baru milik David).

**Pola nama file milik anggota di folder bersama:**
| Folder | Marshal | David | Dafa | Nico |
|---|---|---|---|---|
| `fp/` | `palette*`, `virtual_lab*`, `datagen*`, `designer*`, `registry*`, `strategies*`, `evaluate*`, `validation_*` | `config*`, `io_utils*`, `schemas*`, `orchestrator/` | — | `guardian*`, `market*`, `scout*` |
| `backend/tests/` | `test_{palette,virtual_lab,designer,registry,strategies,evaluate,validation}*` | `conftest.py`, `test_{api,orchestrator,db,services}*` | — | `test_{guardian,market,scout}*` |
| `scripts/` | `generate_data.sh`, `train.sh`, `evaluate.sh` | — | `build_frontend.sh` | sisanya |
| `docs/` | `virtual-lab-model-card.md`, `explainers/marshal.md` | `explainers/david.md` | `explainers/dafa.md` | sisanya |



### 6.4 Instance: port, runtime, log
| Instance | Folder kode | Port | `FP_RUNTIME_DIR` | Yang boleh menyalakan |
|---|---|---|---|---|
| demo | `~/work/release/current` | 8000 | `var/demo/` (di folder release) | Nico |
| marshal | `~/work/formulapilot` | 8001 | `var/marshal/` | Marshal |
| david | `~/work/formulapilot` | 8002 | `var/david/` | David |
| dafa | `~/work/formulapilot` | 8003 | `var/dafa/` | Dafa |
| nico | `~/work/formulapilot` | 8004 | `var/nico/` | Nico |

Isi `FP_RUNTIME_DIR`: `app.db`, `models/`, `logs/app.log`, `run/app.pid`.
- `bash scripts/dev_up.sh <nama>` hanya berjalan jika `<nama>` sama dengan `FP_MEMBER`.
- Opsi reload hanya untuk instance David. Instance lain dinyalakan ulang manual setelah modul berubah.
- Instance tidak berbagi DB atau model. Model dasar dibaca read-only dari `artifacts/models/gp-global-v1.*`.


### 6.5 Status & keputusan per anggota
**`coordination/status/<nama>.md`** (hanya pemilik yang menulis), tabel dengan kolom:
| Kolom | Isi |
|---|---|
| Tugas | ID §18 |
| Status | `TODO` · `DOING` · `STUB` (fungsi publik ada, isi masih fixture) · `DONE` · `BLOCKED (butuh: …)` |
| Waktu | HH:MM |
| Verifikasi | perintah + hasil singkat |
| Catatan | apa yang bisa dipakai anggota lain |

**`coordination/decisions/<nama>.md`**: baris berformat `HH:MM · topik · keputusan · alasan`.

`bash scripts/board.sh` menampilkan gabungan semua status dan request yang belum dijawab (read-only).


### 6.6 Permintaan antar anggota (`coordination/requests/`)
- Pengirim membuat **file baru** `<pengirim>-<HHMM>-<topik>.md` berisi: `Untuk`, `File/Modul`, `Permintaan`, `Alasan`, `Mendesak (ya/tidak)`, dan bagian kosong `## Jawaban`.
- **Hanya penerima** yang mengisi `## Jawaban` (`DITERIMA` / `DITOLAK`, catatan, waktu). Pengirim tidak mengubah file setelah dibuat; revisi = file baru.
- Permintaan mendesak juga diumumkan di grup WhatsApp.


### 6.8 Antrean proses berat (`scripts/heavy.sh <perintah...>`)
Kuota CPU hanya 16 core dan dipakai bersama LLM, jadi hanya **satu** proses berat berjalan pada satu waktu.
1. Ambil kunci eksklusif `var/locks/heavy.lock` (pakai `flock` ⚠️ cek tersedia; jika tidak, kunci berbasis pembuatan folder).
2. Selama menunggu, cetak siapa yang memegang kunci, sejak kapan, dan perintahnya (dibaca dari `var/locks/heavy.owner`).
3. Jalankan perintah dengan `nice -n 10` dan batas thread 8.
4. Lepas kunci dan hapus `heavy.owner` saat selesai maupun gagal.
5. Batas tunggu default 30 menit (`HEAVY_WAIT_MIN`).

Wajib lewat `heavy.sh`: `evaluate.sh`, `generate_data.sh`, `train.sh`, `build_scout.sh`, `fetch_data.sh`, `build_frontend.sh`, `pytest` seluruh folder, dan perintah lain yang melatih model di luar test kecil.

**Batas thread default (`env.sh`):** `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS` = 3; `TOKENIZERS_PARALLELISM=false`. Di dalam `heavy.sh` batas dinaikkan ke 8 dan `joblib` maksimum `n_jobs=8`.


