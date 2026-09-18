# Dafa (C) — Rancangan UI FormulaPilot

Status: C-00 siap direview pengguna; implementasi frontend dimulai pada C-01.
Acuan: PRD v2.0 di docs/PRD.md, identik dengan file Downloads pengguna saat pemeriksaan 17 September 2026.
Pemilik: Dafa. Workspace: ~/work/formulapilot. Instance: dafa, port 8003.

## 1. Tujuan dan batas tahap ini

FormulaPilot membantu formulator memilih eksperimen skincare berikutnya: tentukan target, tinjau kandidat, putuskan, uji, lalu lihat model belajar.
C-00 menghasilkan rancangan tertulis, daftar komponen, pemetaan data, dan wireframe.
Belum ada aplikasi, panggilan API produk, instalasi npm, atau server frontend pada tahap ini.
D-01 sudah DONE saat pemeriksaan. B-01 masih TODO dan fp/schemas.py belum tersedia.
Semua pemetaan di bawah adalah rencana berdasarkan PRD §14.3–14.5, bukan kontrak backend yang sudah diverifikasi.
Saat C-01, cocokkan dengan fp/schemas.py, contracts/api.md, dan fixture milik David tanpa mengedit kontraknya.

## 2. Alur yang akan dilihat pengguna

1. Buka tab Eksperimen dan pilih brief.
2. Periksa atau ubah spesifikasi; pilih jumlah kandidat dan penggunaan orchestrator.
3. Klik Jalankan, lalu lihat status proses dan kandidat.
4. Tinjau komposisi, prediksi beserta rentang 95%, pemeriksaan Guardian, dan bukti jika tersedia.
5. Setujui atau tolak dengan alasan. Status review memerlukan pengakuan telah membaca peringatan; blocked tidak dapat disetujui.
6. Kandidat explore yang disetujui dapat diuji di Virtual Lab; kandidat replay yang disetujui dapat diungkap hasil historisnya.
7. Tampilkan hasil, batch, dan versi model yang dikembalikan backend.
8. Tab Bukti menampilkan evaluasi; tab Agent & Riset merupakan P1.

Explore → formula baru → persetujuan → simulasi → pembaruan model global.
Replay → sesi historis → kandidat pool → persetujuan → ungkap hasil → pembaruan model sesi.
Nilai target default selalu berasal dari Brief.specs; angka ilustrasi wireframe PRD tidak menjadi default baru.

## 3. Wireframe teks

Label di dalam kurung siku adalah tempat data atau aksi, bukan hasil model.

```text
┌ FormulaPilot ─ [sistem] [LLM] [model] [varian] ─ Tentang data ┐
│ [Banner degraded bila diperlukan]                          │
│ Eksperimen          Bukti          Agent & Riset (P1)       │
├──────────────────────┬─────────────────────────────────────┤
│ Panel kiri 380 px    │ Panel kanan fleksibel               │
│ Explore / Replay     │ Timeline agent (P1)                 │
│ Pilih brief          │ Rekomendasi + sumber ringkasan      │
│ Target spesifikasi   ├─────────────────────────────────────┤
│ Jumlah kandidat      │ Kandidat #rank (grid responsif)     │
│ Orchestrator         │ Peluang target · status Guardian    │
│ [Jalankan]           │ Komposisi INCI, %, peran            │
│ Status run           │ Proses: rpm, menit, suhu            │
│                      │ Prediksi dan rentang 95%            │
│ Progres batch        │ Catatan pemeriksaan, bukti          │
│ Target tercapai?     │ [Setujui] [Tolak]                   │
│ [Reset loop]         │ [Uji / Ungkap setelah disetujui]    │
│ Panel sesi replay    │ Hasil uji, batch, versi model baru  │
└──────────────────────┴─────────────────────────────────────┘

Tab Bukti:
[Catatan sumber / banner data contoh bila memenuhi aturan]
[Estimasi penghematan dengan asumsi]
[Closed-loop v1] [Perbandingan v1/v2/v3]
[CV dan kalibrasi] [Replay historis]
[Validasi metode liposom] [Tentang data dan waktu evaluasi]

Tab Agent & Riset (P1):
[Status agent + Run now] [Ringkasan pasar]
[Dokumen riset terbaru jika tersedia] [Riwayat model]
```

Dialog keputusan: pilihan setujui/tolak, alasan minimal 5 karakter,
checkbox peringatan untuk review, tombol simpan dengan loading.
Reset loop memerlukan konfirmasi dan memakai scope global sesuai kontrak.

## 4. Inventaris komponen PRD §15.3

Semua direktori berikut relatif terhadap frontend/src/components/.

| Direktori | Komponen | Tahap |
|---|---|---|
| layout/ | AppHeader, DegradedBanner, Tabs | C-01 |
| layout/ | HonestyNote | C-07 |
| experiment/ | BriefPicker, SpecsEditor, RunControls, RunStatus | C-02 |
| experiment/ | CandidateList, CandidateCard, FormulaTable, PredictionBars, GateBadge, IssueList, SummaryText | C-03 |
| experiment/ | DecisionDialog | C-04 |
| experiment/ | TestButton, LabResultPanel, ProgressPanel, ResetButton | C-05 |
| experiment/ | ModeSwitch, ReplaySessionPanel | C-06 |
| experiment/ | AgentTimeline, EvidenceList | C-08 |
| evidence/ | EvidencePanel, ClosedLoopChart, VariantsChart, CvCards, LiposomeValidationCard, SavingsCard | C-07 |
| agents/ | AgentsStatus, MarketSummary, ResearchFeed, ModelHistory | C-09 |
| common/ | EmptyState, ErrorState, Skeleton, Tooltip | Dipakai sesuai kebutuhan tahap; review lengkap C-10 |

Pendukung: api/client.ts, api/types.ts, lib/format.ts, styles/index.css,
main.tsx, App.tsx, serta hooks useHealth, useBriefs, usePalette, useRun,
useProgress, useEvaluation, useReplaySession, useAgentsStatus.
Rincian replay_historical ditampilkan di EvidencePanel tanpa menambah endpoint.

## 5. Pemetaan kontrak → komponen

Field di tabel memakai nama persis dari PRD. data berarti payload setelah envelope dibuka.

| Sumber / field | Komponen | Perilaku |
|---|---|---|
| Envelope.mode; error.code, error.message, error.request_id | DegradedBanner, ErrorState, api/client.ts | Bedakan mode sistem dan error; request_id dapat dibaca saat gagal |
| health.model_ready, model_version, llm_ready, virtual_lab_variant | AppHeader, RunControls | Model belum siap menonaktifkan aksi run; versi tidak ditebak |
| health.scout_ready, market_ready, evaluation_ready, db_ready, instance | Header / status terkait | Ketidaksiapan fitur ditampilkan sesuai konteks |
| Brief.brief_id, name, description, specs | BriefPicker | Pilihan brief memasok target awal |
| Specs.NIACINAMIDE_MIN_PCT, VISCOSITY_CP, PH, D50_UM_MAX, STABLE, COST_IDR_PER_KG_MAX | SpecsEditor | Validasi rentang §14.3, tampilkan satuan |
| Request run_mode, brief_id, specs, n, use_orchestrator, session_id | RunControls, ModeSwitch | Kirim sesuai mode; jangan mengarang session_id |
| Run.run_id, status, error, created_at, finished_at | RunStatus | Polling tiap 1 detik; berhenti pada done/failed |
| Run.llm_status, model_version, recommendation | AppHeader, SummaryText / rekomendasi | not_used → off; ringkasan kandidat memakai Summary.source |
| Run.candidates; Candidate.candidate_id, rank, origin | CandidateList, CandidateCard | Identitas stabil dan aksi explore/pool yang benar |
| Candidate.formula: GLYCERIN, NIACINAMIDE, CETEARYL_ALCOHOL, EMULSIFIER, CCT, DIMETHICONE, XANTHAN, CARBOMER, NAOH, PHENOXYETHANOL, AQUA | FormulaTable | Komposisi persen; AQUA terakhir; INCI/peran dari palette |
| Candidate.formula.RPM, HMIN, TEMP | FormulaTable | Pisahkan parameter proses dari total persen |
| prediction.VISCOSITY_CP, VISCOSITY_CP_CI95, PH, PH_CI95, D50_UM, D50_UM_CI95 | PredictionBars | Titik, rentang 95%, pita target; viskositas berskala log |
| prediction.P_STABLE, P_SPECS, P_TARGET, UNCERTAINTY, model_version | PredictionBars, CandidateCard | Probabilitas 0–1 diformat persen; jangan menafsirkan null sebagai nol |
| prediction.COST_IDR_PER_KG | FormulaTable / CandidateCard | Rupiah/kg dengan label harga asumsi |
| gate.status; gate.issues[].code, severity, message, field | GateBadge, IssueList, DecisionDialog | pass/review/blocked dan alasan |
| evidence[].type, title, source, detail | EvidenceList | Literatur dan pasar dibedakan menurut type |
| evidence[].detail.pmcid, year, journal, url, score, snippet | EvidenceList | Atribusi literatur dan tautan yang tersedia |
| evidence[].detail.n_products_all, n_indonesia, n_by_segment, examples | EvidenceList | Statistik pasar dari backend |
| summary.text, source, reason | SummaryText | Label llm/template; unavailable menampilkan alasan |
| decision, decision_reason, acknowledged | DecisionDialog | Request menggunakan decision, reason, acknowledged; respons Candidate memakai decision_reason |
| lab_result.lab_result_id, batch_index, outputs, specs_met, source, variant, recorded_at, retrained_model_version | LabResultPanel | Bandingkan target, prediksi, hasil; sumber ditulis eksplisit |
| ProgressSummary.scope, batches, hit_at_batch, best_specs_met, total_specs | ProgressPanel | Hit_at_batch null = belum tercapai; denominator dari total_specs |
| progress riwayat batch: batch_index, candidate_id, specs_met, outputs | ProgressPanel | Nama properti pembungkus riwayat menunggu kontrak David |
| Replay.session_id, seed, known, pool_size, model_version, progress | ReplaySessionPanel | Tampilkan hanya data known; jangan bocorkan hasil pool |
| AgentEvent.seq, agent, action, status, detail, duration_ms, ts | AgentTimeline | after_seq, gabungkan event tanpa duplikasi |
| evaluation.closed_loop.results.v1.curve | ClosedLoopChart | batch dibanding fraksi hit ai/random/heuristic |
| evaluation.closed_loop.results.{v1,v2,v3}.{ai,random,heuristic} | VariantsChart | median, iqr, found_rate sesuai ketersediaan |
| evaluation.cv.{visc,ph,d50,stab} | CvCards | Metrik, baseline, coverage; null = belum tersedia |
| evaluation.replay_historical | EvidencePanel | Bukti replay historis dibedakan dari closed-loop explore |
| evaluation.liposome_validation | LiposomeValidationCard | Data eksperimen nyata (liposom, non-skincare) |
| evaluation.savings_estimate, generated_at, quick, notes | SavingsCard, EvidencePanel, HonestyNote | Asumsi dari payload; label simulasi, sumber, waktu |
| agents/status: designer, guardian, scout, market, scheduler → ready, last_job, next_run | AgentsStatus | Orchestrator juga memakai health/Run; jangan mengasumsikan key orchestrator pada endpoint ini |
| market/summary; models?scope= | MarketSummary, ModelHistory | Bentuk detail diverifikasi dari kontrak pada C-09 |
| Dokumen Scout terbaru | ResearchFeed | Endpoint feed belum ditetapkan §14.5; tunggu kontrak/permintaan ke David, jangan buat endpoint sendiri |

## 6. Aturan aksi dan keadaan UI

- Kandidat blocked: Setujui nonaktif; alasan pemeriksaan tetap terbaca.
- Kandidat review: Setujui memerlukan checkbox; alasan minimal 5 karakter untuk keputusan.
- Setelah keputusan tersimpan, jangan tawarkan keputusan kedua; hormati ALREADY_DECIDED.
- TestButton aktif hanya untuk kandidat approved dan belum memiliki lab_result; aksi menyesuaikan origin.
- Error 409 ditampilkan menurut code dan data terbaru dimuat ulang; jangan menganggap aksi sukses.
- Setiap panel punya loading, kosong, gagal, serta data tersedia. Tombol menampilkan loading dan disabled saat request berlangsung.
- prediction null dan summary unavailable mendapat penjelasan; tidak diisi angka dummy diam-diam.
- Fixture hanya untuk pengembangan dan berlabel DATA CONTOH — bukan hasil model.
- Khusus Bukti, fixture evaluation_min hanya dipakai jika GET /evaluation mengembalikan 404. Gangguan jaringan/500 tetap error.
- Polling events memakai seq terakhir; run baru memiliki state event baru.
- Setelah test/reveal, perbarui kandidat, progress, dan informasi model dari respons/backend.
- Reset global tidak dianggap reset sesi replay.

## 7. Tampilan, sumber, dan proxy

React 18 + TypeScript + Vite, Tailwind CSS, TanStack Query, Recharts, lucide-react; satu halaman dengan tab tanpa router.
Netral terang dengan aksen hijau-teal; status tetap memakai teks/ikon selain warna.
Font sistem dan angka tabular; sasaran layar 1366 serta 1920 px.
Format angka Indonesia, persen, Rupiah; satuan cP, µm, rpm, menit, °C.
Animasi hanya timeline dan loading skeleton.
Vite base './'; request memakai 'api/v1' relatif; trailing slash URL dijaga sesuai PRD.
Port Dafa 8003, proses hanya melalui scripts/dev_up.sh dafa / dev_down.sh dafa.
Build C-01 memakai heavy.sh dan dist.tmp sebelum penggantian dist.

Tentang data wajib menjelaskan:
- Virtual Lab adalah simulator tim dengan persamaan terbuka; angkanya bukan hasil lab nyata.
- Validasi liposom merupakan validasi metode terpisah pada data eksperimen nyata non-skincare.
- Estimasi biaya/waktu adalah asumsi simulasi.
- Pemeriksaan regulasi/sumber bahan memakai label Asumsi tim — perlu verifikasi.
Data produk Open Beauty Facts dipakai untuk bukti pasar/palet bahan, bukan rekonstruksi formula produk nyata.

## 8. Review manual C-00

Di file browser JupyterLab, buka work/formulapilot/docs/explainers/dafa.md.
Gunakan Open With → Markdown Preview jika tersedia.

- [ ] Bagian 2 menjelaskan alur brief → kandidat → keputusan → uji → pembaruan model.
- [ ] Wireframe memiliki Eksperimen, Bukti, dan Agent & Riset (P1).
- [ ] Panel kiri memuat target; panel kanan memuat kandidat dan hasil.
- [ ] Komponen §15.3 terdaftar; status pass/review/blocked memiliki perilaku berbeda.
- [ ] Data simulasi, fixture, hasil model, dan validasi liposom memiliki label terpisah.
- [ ] Pemetaan field jelas bertanda rencana PRD sampai B-01 diverifikasi.
- [ ] Belum ada kebutuhan tampilan tambahan atau koreksi alur dari Dafa.

Pemeriksaan terminal ringan:
```bash
export FP_MEMBER=dafa
source ~/work/formulapilot/scripts/env.sh
test "$FP_MEMBER" = dafa && test -s docs/explainers/dafa.md && echo "C-00: file rancangan tersedia"
cat coordination/status/dafa.md
```

C-00 merupakan review dokumen, jadi belum ada halaman web untuk dites.
Setelah pengguna menyatakan review lulus, cek C-00/B-01/D-02 dan aturan proyek sebelum C-01.
C-11 baru melengkapi explainer dengan file yang benar-benar dibuat, diagram final, serta latihan Q&A.
