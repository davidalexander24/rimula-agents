import { useMemo, useState, useEffect, useRef } from 'react';
import {
  Brain, CheckCircle2, CircleAlert, FlaskConical, Play, RotateCcw, Search, ShieldCheck, Sparkles,
  LoaderCircle, XCircle, AlertTriangle, ChevronDown, Check, History as HistoryIcon,
} from 'lucide-react';
import type { AgentEvent, Brief, Palette, Progress, Run, Specs } from '../../api/types';
import {
  useBriefs, useCreateReplaySession, useCreateRun, usePalette, useProgress, useReplaySession, useResetProgress, useRun,
} from '../../hooks/useWorkspace';
import { ACTION_LABEL, AGENT_LABEL, SPEC_LABEL, SPEC_ORDER, labelStatus, seconds, specTarget } from '../../lib/format';
import { Empty, ErrorState, Loading } from '../common/States';
import { CandidatesComparisonSection } from './CandidateCard';

type Mode = 'explore' | 'replay';


// ---------------------------------------------------------------- Custom Dropdown
interface DropdownOption<T> {
  value: T;
  label: string;
  sublabel?: string;
}

function DropdownSelect<T extends string | number>({
  value,
  options,
  onChange,
  placeholder,
}: {
  value: T;
  options: DropdownOption<T>[];
  onChange: (val: T) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const selectedOption = options.find(o => o.value === value);

  return (
    <div className="custom-dropdown-container" ref={ref}>
      <button
        type="button"
        className={`custom-dropdown-trigger ${open ? 'trigger-open' : ''}`}
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="dropdown-trigger-label">
          {selectedOption ? selectedOption.label : (placeholder ?? 'Pilih…')}
        </span>
        <ChevronDown size={14} className={`dropdown-chevron ${open ? 'chevron-rotated' : ''}`} />
      </button>

      {open && (
        <div className="custom-dropdown-menu" role="listbox">
          {options.map(opt => {
            const isSelected = opt.value === value;
            return (
              <div
                key={String(opt.value)}
                className={`custom-dropdown-item ${isSelected ? 'item-selected' : ''}`}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                role="option"
                aria-selected={isSelected}
              >
                <div className="dropdown-item-text">
                  <span className="dropdown-item-label">{opt.label}</span>
                  {opt.sublabel && <small className="dropdown-item-sublabel">{opt.sublabel}</small>}
                </div>
                {isSelected && <Check size={14} className="dropdown-item-check" />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- spesifikasi

function CleanNumberInput({
  value,
  onChange,
  min,
  max,
  step,
  placeholder,
}: {
  value: number;
  onChange: (val: number) => void;
  min?: number;
  max?: number;
  step?: number | string;
  placeholder?: string;
}) {
  const [str, setStr] = useState(String(value ?? ''));

  useEffect(() => {
    setStr(String(value ?? ''));
  }, [value]);

  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      value={str}
      onChange={e => {
        const v = e.target.value;
        setStr(v);
        if (v !== '' && !isNaN(Number(v))) {
          onChange(Number(v));
        }
      }}
      onBlur={() => {
        if (str === '' || isNaN(Number(str))) {
          const fallback = value ?? min ?? 0;
          setStr(String(fallback));
          onChange(fallback);
        }
      }}
    />
  );
}

function SpecsEditor({ specs, onChange }: { specs: Specs; onChange: (s: Specs) => void }) {
  const range = (key: 'VISCOSITY_CP' | 'PH', i: 0 | 1, v: number) => {
    const next: [number, number] = [specs[key][0], specs[key][1]];
    next[i] = v;
    onChange({ ...specs, [key]: next });
  };
  return (
    <div className="spec-editor">
      <label>
        Niacinamide ≥ (%)
        <CleanNumberInput
          min={0}
          max={10}
          step={0.1}
          value={specs.NIACINAMIDE_MIN_PCT}
          onChange={v => onChange({ ...specs, NIACINAMIDE_MIN_PCT: v })}
        />
      </label>
      <label>
        Viskositas (cP)
        <span className="range-inputs">
          <CleanNumberInput
            min={0}
            step={500}
            value={specs.VISCOSITY_CP[0]}
            onChange={v => range('VISCOSITY_CP', 0, v)}
          />
          <CleanNumberInput
            min={0}
            step={500}
            value={specs.VISCOSITY_CP[1]}
            onChange={v => range('VISCOSITY_CP', 1, v)}
          />
        </span>
      </label>
      <label>
        pH
        <span className="range-inputs">
          <CleanNumberInput
            min={3}
            max={9}
            step={0.1}
            value={specs.PH[0]}
            onChange={v => range('PH', 0, v)}
          />
          <CleanNumberInput
            min={3}
            max={9}
            step={0.1}
            value={specs.PH[1]}
            onChange={v => range('PH', 1, v)}
          />
        </span>
      </label>
      <label>
        Droplet D50 ≤ (µm)
        <CleanNumberInput
          min={0.1}
          step={0.1}
          value={specs.D50_UM_MAX}
          onChange={v => onChange({ ...specs, D50_UM_MAX: v })}
        />
      </label>
      <label>
        Biaya ≤ (Rp/kg)
        <CleanNumberInput
          min={1000}
          step={1000}
          value={specs.COST_IDR_PER_KG_MAX}
          onChange={v => onChange({ ...specs, COST_IDR_PER_KG_MAX: v })}
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={specs.STABLE}
          onChange={e => onChange({ ...specs, STABLE: e.target.checked })}
        />
        Wajib stabil
      </label>
    </div>
  );
}

function specsError(s: Specs): string | null {
  if (s.VISCOSITY_CP[0] >= s.VISCOSITY_CP[1]) return 'Viskositas minimum harus lebih kecil dari maksimum.';
  if (s.PH[0] >= s.PH[1]) return 'pH minimum harus lebih kecil dari maksimum.';
  if (s.NIACINAMIDE_MIN_PCT < 0 || s.NIACINAMIDE_MIN_PCT > 10) return 'Niacinamide minimum harus 0–10%.';
  if (s.D50_UM_MAX <= 0 || s.COST_IDR_PER_KG_MAX <= 0) return 'Droplet dan biaya maksimum harus lebih dari 0.';
  return null;
}

// Batas bawah biaya yang benar-benar bisa dicapai palet: setiap bahan non-air di
// kadar minimumnya (niacinamide mengikuti klaim brief), sisanya air. Semua bahan
// non-air lebih mahal dari air, jadi komposisi ini adalah biaya terendah yang sah.
function minCostIdrPerKg(palette: Palette | undefined, niacinamideMinPct: number): number | null {
  if (!palette || palette.ingredients.length === 0) return null;
  const aqua = palette.ingredients.find(i => i.code === 'AQUA');
  let pct = 0;
  let cost = 0;
  for (const ing of palette.ingredients) {
    if (ing.code === 'AQUA') continue;
    const min = ing.code === 'NIACINAMIDE' ? Math.max(ing.min_pct, niacinamideMinPct) : ing.min_pct;
    if (min > ing.max_pct) return null;
    pct += min;
    cost += (min / 100) * ing.price_idr_per_kg;
  }
  if (pct > 100) return null;
  if (aqua) cost += ((100 - pct) / 100) * aqua.price_idr_per_kg;
  return cost;
}

function specsWarning(s: Specs, palette: Palette | undefined): string | null {
  const floor = minCostIdrPerKg(palette, s.NIACINAMIDE_MIN_PCT);
  if (floor !== null && s.COST_IDR_PER_KG_MAX < floor) {
    const rp = Math.round(floor).toLocaleString('id-ID');
    return `Pada niacinamide ${s.NIACINAMIDE_MIN_PCT}%, biaya bahan terendah yang mungkin dengan palet ini sekitar Rp${rp}/kg. Target biaya di bawah angka itu tidak bisa dipenuhi.`;
  }
  return null;
}

// ---------------------------------------------------------------- timeline

interface Step { key: string; agent: string; action: string; status: string; duration: number | null; detail: Record<string, unknown> }

function groupEvents(events: AgentEvent[]): Step[] {
  const steps: Step[] = [];
  const byCall = new Map<string, Step>();
  for (const e of events) {
    const call = typeof e.detail?.call === 'string' ? e.detail.call : null;
    const existing = call ? byCall.get(call) : undefined;
    if (existing) {
      Object.assign(existing, { status: e.status, duration: e.duration_ms, detail: { ...existing.detail, ...e.detail } });
      continue;
    }
    const step: Step = { key: call ?? `seq-${e.seq}`, agent: e.agent, action: e.action, status: e.status, duration: e.duration_ms, detail: e.detail ?? {} };
    steps.push(step);
    if (call) byCall.set(call, step);
  }
  return steps;
}

function stepNote(s: Step): string {
  const d = s.detail;
  if (s.action === 'propose' && Array.isArray(d.candidate_ids)) return `${d.candidate_ids.length} kandidat`;
  if (s.action === 'check' && typeof d.status === 'string') return labelStatus(d.status);
  if (s.action === 'literature' && typeof d.query === 'string') return `"${d.query}"${typeof d.n_results === 'number' ? ` · ${d.n_results} artikel` : ''}`;
  if (s.action === 'market' && typeof d.n_products_all === 'number') return `${d.n_products_all} produk dengan kombinasi lengkap`;
  if (s.action === 'llm_step' && typeof d.tool_calls === 'number') return `langkah ${String(d.step ?? '')} · ${d.tool_calls} panggilan tool`;
  if (s.action === 'summary_rejected_claim' && Array.isArray(d.offending)) return `kata: ${d.offending.join(', ')}`;
  if (s.action === 'retrain' && typeof d.model_version === 'string') return d.model_version;
  if (s.action === 'error' && typeof d.reason === 'string') return d.reason;
  return '';
}

function AgentTopologyMap({
  run,
  steps,
  highlightedAgent,
  onHoverAgent,
}: {
  run: Run;
  steps: Step[];
  highlightedAgent: string | null;
  onHoverAgent: (agent: string | null) => void;
}) {
  const isRunning = run.status === 'running';

  const designerSteps = steps.filter(s => s.agent === 'designer');
  const guardianSteps = steps.filter(s => s.agent === 'guardian');
  const scoutSteps = steps.filter(s => s.agent === 'scout');
  const orchSteps = steps.filter(s => s.agent === 'orchestrator');

  const designerNote = designerSteps.length > 0
    ? `${run.candidates.length || run.n} usulan formula`
    : 'Menunggu proses';

  const guardianPassCount = run.candidates.filter(c => c.gate.status === 'pass').length;
  const guardianNote = guardianSteps.length > 0
    ? `${run.candidates.length} dicek (${guardianPassCount} lolos)`
    : 'Batas BPOM/Halal';

  const scoutNote = scoutSteps.length > 0
    ? 'Literatur & Pasar'
    : 'Europe PMC · ODbL';

  const labDone = run.candidates.some(c => c.lab_result);
  const labNote = labDone ? 'Uji lab selesai' : 'Menunggu uji lab';

  const orchNote = run.use_orchestrator
    ? `Qwen 30B · ${orchSteps.length || 1} langkah`
    : 'Alur Deterministik';

  const nodes: Record<string, { title: string; subtitle: string; note: string; Icon: typeof Brain }> = {
    orchestrator: { title: 'Orchestrator', subtitle: 'Supervisor Alur', note: orchNote, Icon: Brain },
    designer: { title: 'Designer', subtitle: 'GP + BO', note: designerNote, Icon: Sparkles },
    guardian: { title: 'Guardian', subtitle: 'BPOM & Halal', note: guardianNote, Icon: ShieldCheck },
    scout: { title: 'Scout', subtitle: 'Literatur & Pasar', note: scoutNote, Icon: Search },
    lab: { title: 'Virtual Lab', subtitle: 'Simulasi Emulsi', note: labNote, Icon: FlaskConical },
  };

  return (
    <div className="topology-viewport">
      <svg className="topology-svg" aria-hidden="true">
        <line
          x1="50%" y1="50%" x2="22%" y2="24%"
          className={'topology-edge ' + (highlightedAgent === 'designer' ? 'edge-active' : '')}
        />
        <line
          x1="50%" y1="50%" x2="78%" y2="24%"
          className={'topology-edge ' + (highlightedAgent === 'guardian' ? 'edge-active' : '')}
        />
        <line
          x1="50%" y1="50%" x2="22%" y2="76%"
          className={'topology-edge ' + (highlightedAgent === 'scout' ? 'edge-active' : '')}
        />
        <line
          x1="50%" y1="50%" x2="78%" y2="76%"
          className={'topology-edge ' + (highlightedAgent === 'lab' ? 'edge-active' : '')}
        />
      </svg>

      {(['designer', 'guardian', 'orchestrator', 'scout', 'lab'] as const).map(key => {
        const node = nodes[key];
        const Icon = node.Icon;
        const isActive = highlightedAgent === key;
        const isExecuting = isRunning && isActive;

        return (
          <div
            key={key}
            className={`topology-node node-${key} ${isActive ? 'node-active' : ''} ${isExecuting ? 'node-executing' : ''}`}
            onMouseEnter={() => onHoverAgent(key)}
            onMouseLeave={() => onHoverAgent(null)}
          >
            <div className="node-head">
              <span className="node-icon"><Icon size={13} /></span>
              <strong className="node-title">{node.title}</strong>
              {isExecuting && <span className="node-pulse-dot" title="Sedang Aktif" />}
            </div>
            <span className="node-subtitle">{node.subtitle}</span>
            <span className="node-note">{node.note}</span>
          </div>
        );
      })}
    </div>
  );
}

function AgentTimeline({ run }: { run: Run }) {
  const steps = useMemo(() => groupEvents(run.events), [run.events]);
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null);

  if (!steps.length && run.status !== 'running') return null;

  const isRunning = run.status === 'running';
  const runningStep = steps.find(s => s.status === 'started') ?? steps[steps.length - 1];
  const activeAgent = isRunning ? (runningStep?.agent ?? 'orchestrator') : null;
  const highlightedAgent = isRunning ? activeAgent : hoveredAgent;

  return (
    <section className="timeline-card" aria-live="polite">
      <div className="timeline-header">
        <div>
          <h2>Timeline & Topologi Multi-Agent</h2>
          <span className="timeline-sub">
            {isRunning ? 'Eksperimen sedang berjalan — memantau agen aktif secara real-time' : `Analisis selesai · ${steps.length} langkah terekam`}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isRunning && (
            <span className="running-indicator">
              <LoaderCircle className="spin" size={12} />
              <span>Sedang Berjalan…</span>
            </span>
          )}
          <span className="quiet-label">
            {run.use_orchestrator ? `ORCHESTRATOR · LLM ${run.llm_status.toUpperCase()}` : 'ALUR DETERMINISTIK'}
          </span>
        </div>
      </div>

      <div className="timeline-dual-view">
        {/* Left: Interactive Topology Visualizer */}
        <div className="timeline-topology-col">
          <div className="col-header">
            <span className="eyebrow" style={{ margin: 0 }}>Topologi Interaksi Agent</span>
            {highlightedAgent && (
              <span className="active-agent-pill">
                Sorot: <strong>{AGENT_LABEL[highlightedAgent] ?? highlightedAgent}</strong>
              </span>
            )}
          </div>
          <AgentTopologyMap
            run={run}
            steps={steps}
            highlightedAgent={highlightedAgent}
            onHoverAgent={setHoveredAgent}
          />
        </div>

        {/* Right: Chronological Event Stream */}
        <div className="timeline-stream-col">
          <div className="col-header">
            <span className="eyebrow" style={{ margin: 0 }}>Log Eksekusi ({steps.length} langkah)</span>
            <span className="stream-caption">Arahkan kursor untuk menyorot</span>
          </div>
          <ol className="timeline-stream">
            {steps.map(s => {
              const isItemActive = s.status === 'started';
              const isBlocked = s.action === 'check' && typeof s.detail?.status === 'string' && s.detail.status === 'blocked';
              const isReview = s.action === 'check' && typeof s.detail?.status === 'string' && s.detail.status === 'review';

              return (
                <li
                  key={s.key}
                  className={`stream-step agent-${s.agent} ${s.status === 'failed' || isBlocked ? 'step-blocked' : isReview ? 'step-review' : ''} ${isItemActive ? 'step-running' : ''}`}
                  onMouseEnter={() => setHoveredAgent(s.agent)}
                  onMouseLeave={() => setHoveredAgent(null)}
                >
                  <span className="stream-step-icon">
                    {isItemActive ? (
                      <LoaderCircle className="spin" size={13} />
                    ) : isBlocked ? (
                      <XCircle size={13} />
                    ) : isReview ? (
                      <AlertTriangle size={13} />
                    ) : (
                      <CheckCircle2 size={13} />
                    )}
                  </span>
                  <div className="stream-step-content">
                    <div className="stream-step-head">
                      <strong>{AGENT_LABEL[s.agent] ?? s.agent} · {ACTION_LABEL[s.action] ?? s.action}</strong>
                      <span className="stream-step-time">
                        {s.status === 'started' ? 'Berjalan…' : seconds(s.duration)}
                      </span>
                    </div>
                    {stepNote(s) && <span className="stream-step-note">{stepNote(s)}</span>}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- progress

function ProgressPanel({ progress, scope, onReset, resetting }: { progress?: Progress; scope: string; onReset?: () => void; resetting?: boolean }) {
  const history = progress?.history ?? [];
  return <div className="progress-panel">
    <div className="progress-head"><strong>{scope === 'global' ? 'Loop belajar (global)' : 'Loop sesi replay'}</strong>{onReset && <button className="secondary-button" disabled={resetting} onClick={onReset}><RotateCcw size={13} /> {resetting ? 'Mereset…' : 'Reset loop'}</button>}</div>
    <div className="progress-stats">
      <span><b>{progress?.batches ?? 0}</b>batch diuji</span>
      <span><b>{progress?.best_specs_met ?? 0}/{progress?.total_specs ?? 6}</b>spesifikasi terbaik</span>
      <span><b>{progress?.hit_at_batch ? `batch ${progress.hit_at_batch}` : 'belum'}</b>target tercapai</span>
    </div>
    {history.length > 0 && <ol className="batch-strip" aria-label="Riwayat batch">
      {history.map(h => {
        const met = SPEC_ORDER.filter(k => h.specs_met[k]).length;
        return <li key={h.batch_index} className={h.specs_met.ALL ? 'hit' : ''} title={SPEC_ORDER.map(k => `${SPEC_LABEL[k]} ${h.specs_met[k] ? '✓' : '✗'}`).join(' · ')}>
          <span style={{ height: `${(met / 6) * 100}%` }} /><small>{h.batch_index}</small>
        </li>;
      })}
    </ol>}
  </div>;
}

// ---------------------------------------------------------------- tab

export function ExperimentTab() {
  const briefs = useBriefs();
  const palette = usePalette();
  const create = useCreateRun();
  const reset = useResetProgress();
  const createSession = useCreateReplaySession();
  const [mode, setMode] = useState<Mode>('explore');
  const [briefId, setBriefId] = useState('');
  const [n, setN] = useState(3);
  const [orch, setOrch] = useState(true);
  const [customSpecs, setCustomSpecs] = useState<Specs>();
  const [runIds, setRunIds] = useState<Record<Mode, string | undefined>>({ explore: undefined, replay: undefined });
  const [sessionId, setSessionId] = useState<string>();
  const runId = runIds[mode];
  const run = useRun(runId);
  const session = useReplaySession(mode === 'replay' ? sessionId : undefined);
  const scope = mode === 'replay' && sessionId ? `session:${sessionId}` : 'global';
  const progress = useProgress(scope, mode === 'explore' || Boolean(sessionId));

  const list = briefs.data?.data ?? [];
  const selected: Brief | undefined = list.find(b => b.brief_id === briefId) ?? list[0];
  const specs = mode === 'explore' ? customSpecs ?? selected?.specs : selected?.specs;
  const invalid = specs ? specsError(specs) : null;
  const warning = specs && !invalid ? specsWarning(specs, palette.data?.data) : null;
  const currentRun = run.data?.data;
  const running = currentRun?.status === 'running';

  if (briefs.isPending) return <Loading label="Memuat brief…" />;
  if (briefs.isError) return <ErrorState error={briefs.error} retry={() => void briefs.refetch()} />;

  const start = () => {
    if (!selected) return;
    const body = mode === 'explore'
      ? { run_mode: 'explore' as const, brief_id: selected.brief_id, specs: customSpecs ?? null, n, use_orchestrator: orch }
      : { run_mode: 'replay' as const, brief_id: selected.brief_id, session_id: sessionId ?? null, n, use_orchestrator: orch };
    create.mutate(body, { onSuccess: r => setRunIds(ids => ({ ...ids, [mode]: r.data.run_id })) });
  };
  const newSession = () => selected && createSession.mutate({ brief_id: selected.brief_id }, {
    onSuccess: r => { setSessionId(r.data.session_id); setRunIds(ids => ({ ...ids, replay: undefined })); },
  });
  const runSpecs = currentRun?.specs ?? specs;

  return <div className="experiment-content">
    <aside className="control-card">
      <div className="mode-switch" role="radiogroup" aria-label="Mode kerja">
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'explore'}
          className={mode === 'explore' ? 'active' : ''}
          onClick={() => setMode('explore')}
        >
          <FlaskConical size={13} />
          <span>Virtual Lab</span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'replay'}
          className={mode === 'replay' ? 'active' : ''}
          onClick={() => setMode('replay')}
        >
          <HistoryIcon size={13} />
          <span>Data Historis</span>
        </button>
      </div>
      <p className="muted small">{mode === 'explore'
        ? 'Designer mengusulkan formula baru; formula yang disetujui diuji di Virtual Lab (simulasi), lalu model dilatih ulang.'
        : 'Mulai dari 10 formula historis yang belum lolos. Designer memilih dari pool data historis; hasilnya baru terlihat setelah diungkap.'}</p>

      <div className="dropdown-field">
        <label className="dropdown-label">Brief Formulasi (titik awal)</label>
        <DropdownSelect
          value={selected?.brief_id ?? ''}
          options={list.map(b => ({
            value: b.brief_id,
            label: b.name,
            sublabel: b.description,
          }))}
          onChange={val => {
            setBriefId(val);
            setCustomSpecs(undefined);
            setSessionId(undefined);
          }}
          placeholder="Pilih brief formula…"
        />
      </div>

      {specs && <div className="spec-summary">
        <div className="spec-summary-head">
          <span className="eyebrow">SPESIFIKASI TARGET{mode === 'explore' && customSpecs ? ' · DISESUAIKAN' : ''}</span>
          {mode === 'explore' && customSpecs && <button className="text-button" onClick={() => setCustomSpecs(undefined)}>Kembalikan ke brief</button>}
        </div>
        {mode === 'explore' ? <>
          <p className="muted small">Target ini bisa diubah sepenuhnya. Brief di atas hanya mengisi angka awal; ubah nilai mana pun sebelum menjalankan.</p>
          <SpecsEditor specs={specs} onChange={setCustomSpecs} />
        </> : <ul>{SPEC_ORDER.map(k => <li key={k}><span>{SPEC_LABEL[k]}</span><b>{specTarget(k, specs)}</b></li>)}</ul>}
        {invalid && <p className="inline-error small">{invalid}</p>}
        {warning && <p className="inline-error small">{warning}</p>}
      </div>}

      {mode === 'replay' && <div className="replay-panel">
        <button className="secondary-button wide" disabled={createSession.isPending || running} onClick={newSession}>{createSession.isPending ? 'Menyiapkan sesi…' : sessionId ? 'Mulai sesi baru' : 'Mulai sesi replay'}</button>
        {createSession.error && <p className="inline-error small">{createSession.error.message}</p>}
        {session.data && <div className="session-info">
          <span>Sesi <b>{session.data.data.session_id}</b></span>
          <span>{session.data.data.known.length} formula diketahui · {session.data.data.pool_size} di pool</span>
          <span>Model sesi <b>{session.data.data.model_version}</b></span>
        </div>}
      </div>}

      <div className="run-controls">
        <div className="dropdown-field" style={{ margin: '0 0 12px 0' }}>
          <label className="dropdown-label">Jumlah Kandidat</label>
          <DropdownSelect
            value={n}
            options={[1, 2, 3, 4, 5].map(x => ({
              value: x,
              label: `${x} kandidat`,
            }))}
            onChange={val => setN(Number(val))}
          />
        </div>
        <label className="check"><input type="checkbox" checked={orch} onChange={e => setOrch(e.target.checked)} /> Orchestrator LLM (Qwen3 lokal)</label>
      </div>
      <button className="primary-button wide" disabled={!selected || create.isPending || running || Boolean(invalid) || (mode === 'replay' && !sessionId)} onClick={start}>
        <Play size={15} /> {create.isPending ? 'Mengirim…' : running ? 'Run berjalan…' : mode === 'replay' && !sessionId ? 'Mulai sesi dulu' : 'Jalankan'}
      </button>
      {create.error && <p className="inline-error small">{create.error.message}</p>}

      <ProgressPanel progress={progress.data?.data} scope={scope}
        onReset={mode === 'explore' ? () => { if (window.confirm('Reset loop global? Hasil uji diarsipkan dan model kembali ke gp-global-v1.')) reset.mutate({ scope: 'global' }); } : undefined}
        resetting={reset.isPending} />
      {reset.error && <p className="inline-error small">{reset.error.message}</p>}
    </aside>

    <section className="results-column">
      {!runId && <div className="results-card"><Empty title={mode === 'replay' && !sessionId ? 'Belum ada sesi replay' : 'Belum ada run'}>{mode === 'replay' && !sessionId ? 'Mulai sesi replay, lalu jalankan Designer pada pool data historis.' : 'Pilih brief lalu jalankan eksperimen.'}</Empty></div>}
      {runId && run.isPending && <div className="results-card"><Loading label="Menunggu run…" /></div>}
      {run.isError && <div className="results-card"><ErrorState error={run.error} retry={() => void run.refetch()} /></div>}
      {currentRun && <>
        <div className="run-status">
          <span className={'run-dot status-' + currentRun.status}>{running ? <CircleAlert size={15} /> : <CheckCircle2 size={15} />} {labelStatus(currentRun.status)}</span>
          <span>{currentRun.run_mode === 'replay' ? 'Replay' : 'Explore'} · {currentRun.candidates.length}/{currentRun.n} kandidat · model {currentRun.model_version}</span>
          {currentRun.finished_at && <span>{seconds(new Date(currentRun.finished_at).getTime() - new Date(currentRun.created_at).getTime())}</span>}
        </div>
        {currentRun.error && <p className="inline-error">{currentRun.error}</p>}
        <AgentTimeline run={currentRun} />
        {currentRun.recommendation && <p className="recommendation"><b>Rekomendasi:</b> {currentRun.recommendation}</p>}
        {runSpecs && (
          <CandidatesComparisonSection
            candidates={currentRun.candidates}
            specs={runSpecs}
            palette={palette.data?.data}
            runDone={currentRun.status === 'done'}
          />
        )}
        {currentRun.status === 'done' && currentRun.candidates.length === 0 && <Empty title="Tidak ada kandidat">Designer tidak mengusulkan kandidat untuk spesifikasi ini.</Empty>}
      </>}
    </section>
  </div>;
}
