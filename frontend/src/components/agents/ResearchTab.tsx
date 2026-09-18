import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Play } from 'lucide-react';
import type { AgentStatus } from '../../api/types';
import { useAgentsStatus, useMarketSummary, useModels, useRunAgent } from '../../hooks/useWorkspace';
import { INCI_FALLBACK, dateTimeId, labelStatus, numberId, percentId } from '../../lib/format';
import { Empty, ErrorState, Loading } from '../common/States';

const AGENTS = [
  { key: 'designer', name: 'Designer', job: 'Latih ulang model global', runnable: true },
  { key: 'guardian', name: 'Guardian', job: 'Periksa ulang kandidat terakhir', runnable: true },
  { key: 'scout', name: 'Scout · literatur', job: 'Muat ulang indeks & data pasar', runnable: true },
  { key: 'market', name: 'Scout · pasar', job: 'Open Beauty Facts', runnable: false },
  { key: 'scheduler', name: 'Penjadwal', job: 'Job otomatis (P2)', runnable: false },
] as const;

function AgentCard({ name, job, status, runnable, agentKey }: { name: string; job: string; status?: AgentStatus; runnable: boolean; agentKey: string }) {
  const run = useRunAgent();
  const last = status?.last_job;
  const busy = last?.status === 'queued' || last?.status === 'running';

  return (
    <div className="agent-card">
      <div className="agent-card-head">
        <div className="agent-card-info">
          <strong className="agent-card-title">{name}</strong>
          <small className="agent-card-job">{job}</small>
        </div>
        <span className={'status-pill ' + (status?.ready ? 'status-ready' : '')}>
          <span className="status-dot" />
          {status?.ready ? 'Siap' : 'Belum siap'}
        </span>
      </div>

      {last ? (
        <p className="small muted">
          Job terakhir: {labelStatus(last.status)} · {dateTimeId(last.finished_at ?? last.started_at)}
          {typeof last.detail?.error === 'string' && <span className="inline-error"> · {last.detail.error}</span>}
          {typeof last.detail?.model_version === 'string' && <> · {last.detail.model_version}</>}
        </p>
      ) : (
        <p className="small muted">Belum ada job.</p>
      )}

      {runnable && (
        <button
          className="secondary-button"
          disabled={busy || run.isPending}
          onClick={() => run.mutate(agentKey)}
        >
          <Play size={12} />
          <span>{busy ? 'Berjalan…' : 'Jalankan sekarang'}</span>
        </button>
      )}
      {run.error && <p className="inline-error small">{run.error.message}</p>}
    </div>
  );
}

function MarketSummary() {
  const m = useMarketSummary();
  if (m.isPending) return <Loading label="Memuat data pasar…" />;
  if (m.isError) return <Empty title="Data pasar belum tersedia">{m.error.message}</Empty>;
  const d = m.data.data as { n_products?: number; n_indonesia?: number; n_by_segment?: Record<string, number>; prevalence?: Record<string, number>; built_at?: string; license?: string };
  const prevalence = Object.entries(d.prevalence ?? {}).map(([code, v]) => ({ name: INCI_FALLBACK[code] ?? code, value: v })).sort((a, b) => b.value - a.value);
  return <>
    <div className="market-stats">
      <span><b>{numberId(d.n_products, 0)}</b>produk skincare/makeup</span>
      {Object.entries(d.n_by_segment ?? {}).map(([seg, v]) => <span key={seg}><b>{numberId(v, 0)}</b>{seg}</span>)}
      <span><b>{numberId(d.n_indonesia, 0)}</b>di Indonesia</span>
    </div>
    <p className="chart-title">Proporsi produk yang memuat bahan palet</p>
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={prevalence} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid stroke="#e7ece7" horizontal={false} />
        <XAxis type="number" tickFormatter={v => percentId(Number(v))} tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 11 }} />
        <Tooltip formatter={value => percentId(Number(value), 1)} />
        <Bar dataKey="value" name="Proporsi produk" fill="var(--ink-primary)" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
    <p className="muted small">Sumber: Open Beauty Facts ({d.license ?? 'ODbL'}) · dibangun {dateTimeId(d.built_at)}. Nama merek hanya ditampilkan sebagai contoh produk publik dengan atribusi.</p>
  </>;
}

function ModelHistory() {
  const models = useModels();
  if (models.isPending) return <Loading />;
  if (models.isError) return <ErrorState error={models.error} />;
  const rows = models.data.data;
  if (!rows.length) return <Empty title="Belum ada versi model" />;
  return <table className="model-table">
    <thead><tr><th>Versi</th><th>Scope</th><th className="num">Data latih</th><th>Induk</th><th>Waktu</th></tr></thead>
    <tbody>{rows.slice(0, 15).map(v => <tr key={v.version} className={v.is_active ? 'active-row' : ''}><td>{v.version}{v.is_active && <em> aktif</em>}</td><td>{v.scope}</td><td className="num">{numberId(v.n_train, 0)}</td><td>{v.parent_version ?? '—'}</td><td>{dateTimeId(v.created_at)}</td></tr>)}</tbody>
  </table>;
}

export function ResearchTab() {
  const agents = useAgentsStatus(true);
  return <div className="research-layout">
    <section className="evidence-card wide-card">
      <p className="eyebrow">STATUS AGENT</p>
      {agents.isPending ? <Loading /> : agents.isError ? <ErrorState error={agents.error} retry={() => void agents.refetch()} /> :
        <div className="agent-grid">
          {AGENTS.map(a => (
            <AgentCard
              key={a.key}
              agentKey={a.key}
              name={a.name}
              job={a.job}
              runnable={a.runnable}
              status={(agents.data.data as unknown as Record<string, AgentStatus>)[a.key]}
            />
          ))}
        </div>}
    </section>
    <div className="evidence-two">
      <section className="evidence-card"><p className="eyebrow">DATA PASAR · OPEN BEAUTY FACTS</p><MarketSummary /></section>
      <section className="evidence-card"><p className="eyebrow">RIWAYAT MODEL DESIGNER</p><ModelHistory />
        <p className="muted small">Literatur Europe PMC per kandidat tampil di kartu kandidat (tab Eksperimen).</p></section>
    </div>
  </div>;
}
