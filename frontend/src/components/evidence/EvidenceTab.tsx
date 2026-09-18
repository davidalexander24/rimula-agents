import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useEvaluation } from '../../hooks/useWorkspace';
import { dateTimeId, numberId, percentId, rupiah } from '../../lib/format';
import { ErrorState, Loading } from '../common/States';

interface Summary { median: number | null; iqr: [number | null, number | null]; found_rate: number | null; n_found?: number; n_seeds?: number }
interface CurvePoint { batch: number; ai?: number | null; random?: number | null; heuristic?: number | null }
type StrategyBlock = { ai?: Summary; random?: Summary; heuristic?: Summary; curve?: CurvePoint[] };
interface Report {
  generated_at: string; quick: boolean; brief_id: string; unc_max: number | null; runtime_seconds: number | null; notes: string[];
  hit_rate_random: Record<string, number | null>;
  cv: { n?: number; folds?: number; visc?: Record<string, number | null>; ph?: Record<string, number | null>; d50?: Record<string, number | null>; stab?: Record<string, number | null> };
  closed_loop: { max_batches?: number; seeds?: number; start_known?: number; results?: Record<string, StrategyBlock> };
  replay_historical: StrategyBlock & { max_steps?: number; seeds?: number; pool?: number; pool_hits?: number };
  liposome_validation: {
    rows?: number | null; hits?: number | null; label?: string; license?: string; max_steps?: number; seeds?: number;
    cv?: Record<string, number | null>; replay?: { ai?: Summary; random?: Summary }; curve?: CurvePoint[];
  };
  savings_estimate: { label?: string; batches_saved?: number | null; cost_saved_idr?: number | null; days_saved?: number | null; basis?: string; assumptions?: { cost_per_batch_idr?: number; days_per_batch?: number } };
}

const COLORS = { ai: '#1f6f5c', random: '#9aa5a0', heuristic: '#d08c2a' };
const NAMES = { ai: 'AI (Rimula Agents)', random: 'Acak', heuristic: 'Heuristik formulator' };
const pct = (v: unknown) => percentId(typeof v === 'number' ? v : Number(v));

export function HonestyNote() {
  return <aside className="honesty-note">
    <strong>Pernyataan kejujuran</strong>
    <ul>
      <li>Virtual Lab adalah <b>simulator buatan tim</b> dengan persamaan terbuka. Arah hubungan antarvariabel mengacu literatur, tetapi angkanya bukan hasil lab nyata.</li>
      <li>Kemampuan metode pada <b>data eksperimen nyata</b> ditunjukkan terpisah pada dataset liposom publik (non-skincare), hanya untuk validasi.</li>
      <li>Semua estimasi biaya dan waktu adalah asumsi simulasi.</li>
    </ul>
  </aside>;
}

function StrategyStat({ label, s, max }: { label: string; s?: Summary; max?: number }) {
  return <div className="strategy-stat">
    <small>{label}</small>
    <b>{s?.median == null ? '—' : s.median > (max ?? Infinity) ? `> ${numberId(max, 0)}` : numberId(s.median, 1)}</b>
    <span>median batch · IQR {numberId(s?.iqr?.[0], 1)}–{numberId(s?.iqr?.[1], 1)}</span>
    <span>ketemu {percentId(s?.found_rate)}{s?.n_seeds ? ` dari ${s.n_seeds} seed` : ''}</span>
  </div>;
}

function SavingsCard({ r }: { r: Report }) {
  const s = r.savings_estimate;
  const v1 = r.closed_loop.results?.v1;
  const saved = s.batches_saved ?? null;
  return <section className="evidence-card savings-card">
    <p className="eyebrow">ESTIMASI SIMULASI</p>
    {saved != null && saved > 0 ? <div className="savings-grid">
      <div><b>{numberId(saved, 1)}</b><span>batch uji dihemat</span></div>
      <div><b>{rupiah(s.cost_saved_idr)}</b><span>biaya dihemat</span></div>
      <div><b>{numberId(s.days_saved, 0)}</b><span>hari dihemat</span></div>
    </div> : <p className="muted">Tidak ada penghematan pada simulasi ini — tidak diklaim.</p>}
    <p className="muted small">Estimasi simulasi — asumsi biaya {rupiah(s.assumptions?.cost_per_batch_idr)}/batch, {numberId(s.assumptions?.days_per_batch, 0)} hari/batch. Dasar: median batch strategi acak − AI pada Virtual Lab v1.</p>
    {v1 && <div className="strategy-row">
      <StrategyStat label={NAMES.ai} s={v1.ai} max={r.closed_loop.max_batches} />
      <StrategyStat label={NAMES.random} s={v1.random} max={r.closed_loop.max_batches} />
      <StrategyStat label={NAMES.heuristic} s={v1.heuristic} max={r.closed_loop.max_batches} />
    </div>}
  </section>;
}

function CurveChart({ data, keys, xLabel }: { data: CurvePoint[]; keys: (keyof typeof NAMES)[]; xLabel: string }) {
  return <ResponsiveContainer width="100%" height={260}>
    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
      <CartesianGrid stroke="#e7ece7" vertical={false} />
      <XAxis dataKey="batch" tick={{ fontSize: 11 }} label={{ value: xLabel, position: 'insideBottom', offset: -8, fontSize: 11 }} />
      <YAxis tick={{ fontSize: 11 }} domain={[0, 1]} tickFormatter={pct} width={44} />
      <Tooltip formatter={value => pct(value)} labelFormatter={l => `${xLabel} ${String(l)}`} />
      <Legend wrapperStyle={{ fontSize: 12 }} verticalAlign="top" height={28} />
      {keys.map(k => <Line key={k} type="stepAfter" dataKey={k} name={NAMES[k]} stroke={COLORS[k]} strokeWidth={k === 'ai' ? 3 : 2} dot={false} isAnimationActive={false} />)}
    </LineChart>
  </ResponsiveContainer>;
}

function ClosedLoopCard({ r }: { r: Report }) {
  const cl = r.closed_loop;
  const v1 = cl.results?.v1;
  const variants = ['v1', 'v2', 'v3'].filter(v => cl.results?.[v]?.ai);
  const bars = variants.map(v => ({ variant: v, ai: cl.results?.[v]?.ai?.median ?? null, random: cl.results?.[v]?.random?.median ?? null, heuristic: cl.results?.[v]?.heuristic?.median ?? null }));
  return <section className="evidence-card wide-card">
    <div className="card-head"><div><p className="eyebrow">SKENARIO A · CLOSED-LOOP VIRTUAL LAB (SIMULASI)</p><h3>Berapa batch uji sampai formula memenuhi semua spesifikasi?</h3></div>
      <span className="quiet-label">{cl.seeds} SEED · MULAI {cl.start_known} FORMULA · MAKS {cl.max_batches} BATCH</span></div>
    <div className="chart-pair">
      <div><p className="chart-title">Fraksi seed yang sudah menemukan formula lolos — varian v1</p>{v1?.curve ? <CurveChart data={v1.curve} keys={['ai', 'random', 'heuristic']} xLabel="Batch" /> : <p className="muted">Kurva belum tersedia.</p>}</div>
      <div><p className="chart-title">Median batch per varian simulator (lebih rendah lebih baik; tidak ketemu = {(cl.max_batches ?? 40) + 1})</p>
        {bars.length ? <ResponsiveContainer width="100%" height={260}>
          <BarChart data={bars} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="#e7ece7" vertical={false} />
            <XAxis dataKey="variant" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} width={36} />
            <Tooltip formatter={value => numberId(Number(value), 1)} />
            <Legend wrapperStyle={{ fontSize: 12 }} verticalAlign="top" height={28} />
            {(['ai', 'random', 'heuristic'] as const).map(k => <Bar key={k} dataKey={k} name={NAMES[k]} fill={COLORS[k]} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer> : <p className="muted">Belum ada data varian.</p>}
      </div>
    </div>
    <p className="muted small">Hit rate formula acak: {Object.entries(r.hit_rate_random).map(([v, x]) => `${v} ${percentId(x, 1)}`).join(' · ')}.</p>
  </section>;
}

function ReplayCard({ r }: { r: Report }) {
  const rh = r.replay_historical;
  return <section className="evidence-card">
    <p className="eyebrow">SKENARIO B · REPLAY DATA HISTORIS (SIMULASI)</p>
    <h3>Memilih dari {numberId(rh.pool, 0)} catatan lab lama ({numberId(rh.pool_hits, 0)} yang lolos)</h3>
    {rh.curve && <CurveChart data={rh.curve} keys={['ai', 'random', 'heuristic']} xLabel="Langkah" />}
    <div className="strategy-row">
      <StrategyStat label={NAMES.ai} s={rh.ai} max={rh.max_steps} />
      <StrategyStat label={NAMES.random} s={rh.random} max={rh.max_steps} />
      <StrategyStat label={NAMES.heuristic} s={rh.heuristic} max={rh.max_steps} />
    </div>
  </section>;
}

function LiposomeCard({ r }: { r: Report }) {
  const lv = r.liposome_validation;
  if (lv.rows == null) return <section className="evidence-card"><p className="eyebrow">SKENARIO C · DATA EKSPERIMEN NYATA</p><p className="muted">Validasi liposom belum dijalankan.</p></section>;
  return <section className="evidence-card real-data">
    <p className="eyebrow">SKENARIO C · DATA EKSPERIMEN NYATA (LIPOSOM, NON-SKINCARE)</p>
    <h3>Validasi metode pada {numberId(lv.rows, 0)} formulasi liposom ({numberId(lv.hits, 0)} memenuhi target 100–150 nm, PDI &lt; 0,15)</h3>
    {lv.curve && <CurveChart data={lv.curve} keys={['ai', 'random']} xLabel="Langkah" />}
    <div className="strategy-row">
      <StrategyStat label={NAMES.ai} s={lv.replay?.ai} max={lv.max_steps} />
      <StrategyStat label={NAMES.random} s={lv.replay?.random} max={lv.max_steps} />
      <div className="strategy-stat"><small>Akurasi model (CV 5-fold)</small><b>R² {numberId(lv.cv?.log_size_r2, 2)}</b><span>ukuran (log) · PDI (log) R² {numberId(lv.cv?.log_pdi_r2, 2)}</span><span>galat median ukuran {numberId(lv.cv?.size_nm_median_ae, 1)} nm</span></div>
    </div>
    <p className="muted small">Sumber: Zenodo 17867478 · {lv.license}. Dipakai hanya untuk validasi metode, bukan untuk melatih model skincare.</p>
  </section>;
}

function CvCards({ r }: { r: Report }) {
  const cv = r.cv;
  const cards = [
    { name: 'Viskositas', main: `R² ${numberId(cv.visc?.r2, 3)}`, sub: `galat median ${numberId(cv.visc?.median_abs_cp, 0)} cP`, cov: cv.visc?.coverage95 },
    { name: 'pH', main: `R² ${numberId(cv.ph?.r2, 3)}`, sub: `MAE ${numberId(cv.ph?.mae, 2)}`, cov: cv.ph?.coverage95 },
    { name: 'Droplet D50', main: `R² ${numberId(cv.d50?.r2, 3)}`, sub: `MAE ${numberId(cv.d50?.mae_um, 2)} µm`, cov: cv.d50?.coverage95 },
    { name: 'Stabilitas', main: `AUC ${numberId(cv.stab?.auc, 3)}`, sub: `Brier ${numberId(cv.stab?.brier, 3)} vs baseline ${numberId(cv.stab?.baseline_brier, 3)}`, cov: undefined },
  ];
  return <section className="evidence-card wide-card">
    <div className="card-head"><div><p className="eyebrow">AKURASI MODEL · CV {cv.folds ?? 5}-FOLD PADA {numberId(cv.n, 0)} CATATAN HISTORIS (SIMULASI)</p><h3>Seberapa tepat prediksi Designer?</h3></div>
      <span className="quiet-label">BASELINE R² = 0</span></div>
    <div className="cv-grid">
      {cards.map(c => <div key={c.name} className="cv-card"><small>{c.name}</small><b>{c.main}</b><span>{c.sub}</span>{c.cov != null && <span>Rentang 95% memuat nilai aktual: {percentId(c.cov)}</span>}</div>)}
    </div>
    <p className="muted small">Ambang ketidakpastian tinggi Guardian (persentil 80): {numberId(r.unc_max, 3)}.</p>
  </section>;
}

export function EvidenceTab() {
  const q = useEvaluation();
  if (q.isPending) return <Loading label="Memuat evaluasi…" />;
  if (q.isError) return <ErrorState error={q.error} retry={() => void q.refetch()} />;
  const r = q.data.data as unknown as Report;
  return <div className="evidence-layout">
    {q.data.fixture && <div className="example-banner">DATA CONTOH — bukan hasil model</div>}
    {r.quick && <div className="example-banner">Evaluasi cepat (--quick): jumlah seed terbatas, angka bisa berubah.</div>}
    <SavingsCard r={r} />
    <ClosedLoopCard r={r} />
    <div className="evidence-two">
      <ReplayCard r={r} />
      <LiposomeCard r={r} />
    </div>
    <CvCards r={r} />
    <HonestyNote />
    <footer className="evidence-footer">
      Dibuat {dateTimeId(r.generated_at)} · sumber artifacts/evaluation.json · brief {r.brief_id} · runtime {numberId(r.runtime_seconds, 0)} dtk · model card: docs/virtual-lab-model-card.md
      {r.notes?.length > 0 && <ul>{r.notes.map(n => <li key={n}>{n}</li>)}</ul>}
    </footer>
  </div>;
}
