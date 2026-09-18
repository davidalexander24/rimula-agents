import { useState } from 'react';
import {
  BookOpen, Check, ExternalLink, FlaskConical, History, ShoppingBag, X,
  CheckCircle2, AlertTriangle, XCircle, ChevronRight,
} from 'lucide-react';
import type { Candidate, Evidence, Issue, LabResult, Palette, Specs } from '../../api/types';
import { useDecision, useRevealCandidate, useTestCandidate } from '../../hooks/useWorkspace';
import {
  ASSUMPTION_NOTE, GATE_LABEL, INCI_FALLBACK, INGREDIENTS, SPEC_LABEL, SPEC_ORDER, SUMMARY_SOURCE_LABEL,
  numberId, pairLabel, percentId, rupiah, specTarget,
} from '../../lib/format';

export function GateBadge({ status }: { status: string }) {
  const Icon = status === 'pass' ? CheckCircle2 : status === 'review' ? AlertTriangle : XCircle;
  return (
    <span className={'gate gate-' + status}>
      <Icon size={12} />
      <span>{GATE_LABEL[status] ?? status}</span>
    </span>
  );
}

// ---------------------------------------------------------------- Mini Gauge for Compact Card
function MiniGauge({ label, value, specLo, specHi, domain, log = false }: {
  label: string; value: number; specLo: number; specHi: number; domain: [number, number]; log?: boolean;
}) {
  const t = (v: number) => (log ? Math.log10(Math.max(v, 1e-9)) : v);
  const pos = (v: number) => Math.min(100, Math.max(0, ((t(v) - t(domain[0])) / (t(domain[1]) - t(domain[0]))) * 100));
  const ok = value >= specLo && value <= specHi;
  const left = pos(specLo);
  const width = Math.max(pos(specHi) - left, 4);

  return (
    <div className="mini-gauge">
      <span className="mini-gauge-label">{label}</span>
      <div className="mini-gauge-track">
        <span className="mini-gauge-spec" style={{ left: `${left}%`, width: `${width}%` }} />
        <span className={'mini-gauge-dot ' + (ok ? 'dot-ok' : 'dot-miss')} style={{ left: `${pos(value)}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Compact Card (Top Grid)
function CandidateCompactCard({
  candidate,
  specs,
  isSelected,
  onSelect,
}: {
  candidate: Candidate;
  specs: Specs;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const p = candidate.prediction;
  const f = candidate.formula;
  const niacOk = f.NIACINAMIDE >= specs.NIACINAMIDE_MIN_PCT;
  const stabOk = p ? p.P_STABLE >= 0.5 : true;

  return (
    <div
      className={`compact-card ${isSelected ? 'compact-card-selected' : ''}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onSelect(); }}
    >
      <div className="compact-card-head">
        <div className="compact-card-title">
          <span className="compact-rank">KANDIDAT #{candidate.rank}</span>
        </div>
        <GateBadge status={candidate.gate.status} />
      </div>

      <div className="compact-metric-block">
        <div className="compact-metric-main">
          <span className="compact-target-val">{p ? percentId(p.P_TARGET) : '—'}</span>
          <span className="compact-target-sub">peluang seluruh spesifikasi</span>
        </div>
        {p && (
          <div className="compact-diff-row">
            <span className={`compact-diff-pill ${candidate.rank === 1 ? 'pill-optimal' : ''}`}>
              {candidate.rank === 1 ? 'Optimal · Biaya Terendah' : `Variasi #${candidate.rank}`} · {rupiah(p.COST_IDR_PER_KG)}
            </span>
          </div>
        )}
      </div>

      {p && (
        <div className="compact-gauges">
          <MiniGauge
            label="visk"
            value={p.VISCOSITY_CP}
            specLo={specs.VISCOSITY_CP[0]}
            specHi={specs.VISCOSITY_CP[1]}
            domain={[Math.min(specs.VISCOSITY_CP[0], p.VISCOSITY_CP_CI95[0]) / 2, Math.max(specs.VISCOSITY_CP[1], p.VISCOSITY_CP_CI95[1]) * 2]}
            log
          />
          <MiniGauge
            label="pH"
            value={p.PH}
            specLo={specs.PH[0]}
            specHi={specs.PH[1]}
            domain={[Math.min(specs.PH[0], p.PH_CI95[0]) - 0.5, Math.max(specs.PH[1], p.PH_CI95[1]) + 0.5]}
          />
          <MiniGauge
            label="D50"
            value={p.D50_UM}
            specLo={0}
            specHi={specs.D50_UM_MAX}
            domain={[0, Math.max(specs.D50_UM_MAX, p.D50_UM_CI95[1]) * 1.3]}
          />
        </div>
      )}

      <div className="compact-chips">
        {p && (
          <span className={`compact-chip ${stabOk ? 'chip-ok' : 'chip-miss'}`}>
            Peluang stabil {percentId(p.P_STABLE)}
          </span>
        )}
        <span className={`compact-chip ${niacOk ? 'chip-ok' : 'chip-miss'}`}>
          Niacinamide {numberId(f.NIACINAMIDE, 2)}% (≥ {numberId(specs.NIACINAMIDE_MIN_PCT, 0)}%)
        </span>
      </div>

      <div className={`compact-link ${isSelected ? 'selected' : ''}`}>
        {isSelected ? 'Terbuka di bawah ↓' : 'Buka detail →'}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Comparison Table (Top Table View)
function CandidateComparisonTable({
  candidates,
  specs,
  selectedId,
  onSelect,
}: {
  candidates: Candidate[];
  specs: Specs;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="compare-table-wrapper">
      <table className="compare-table">
        <thead>
          <tr>
            <th className="th-metric">METRIK</th>
            {candidates.map(c => (
              <th
                key={c.candidate_id}
                className={`th-candidate ${c.candidate_id === selectedId ? 'th-selected' : ''}`}
                onClick={() => onSelect(c.candidate_id)}
              >
                <div className="th-candidate-title">KANDIDAT #{c.rank}</div>
                <div className="th-candidate-gate"><GateBadge status={c.gate.status} /></div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Row: P_TARGET */}
          <tr>
            <td className="td-label">P_TARGET</td>
            {candidates.map(c => {
              const p = c.prediction;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <strong style={{ color: p && p.P_TARGET >= 0.7 ? 'var(--status-pass-ink)' : 'var(--ink-primary)' }}>
                    {p ? percentId(p.P_TARGET) : '—'}
                  </strong>
                </td>
              );
            })}
          </tr>

          {/* Row: Viskositas */}
          <tr>
            <td className="td-label">Viskositas (cP)</td>
            {candidates.map(c => {
              const p = c.prediction;
              const val = p?.VISCOSITY_CP ?? 0;
              const ok = val >= specs.VISCOSITY_CP[0] && val <= specs.VISCOSITY_CP[1];
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{p ? numberId(val, 0) : '—'}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: pH */}
          <tr>
            <td className="td-label">pH</td>
            {candidates.map(c => {
              const p = c.prediction;
              const val = p?.PH ?? 0;
              const ok = val >= specs.PH[0] && val <= specs.PH[1];
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{p ? numberId(val, 2) : '—'}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: Droplet D50 */}
          <tr>
            <td className="td-label">Droplet D50 (µm)</td>
            {candidates.map(c => {
              const p = c.prediction;
              const val = p?.D50_UM ?? 0;
              const ok = val <= specs.D50_UM_MAX;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{p ? numberId(val, 2) : '—'}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: Niacinamide */}
          <tr>
            <td className="td-label">Niacinamide (%)</td>
            {candidates.map(c => {
              const val = c.formula.NIACINAMIDE;
              const ok = val >= specs.NIACINAMIDE_MIN_PCT;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{numberId(val, 2)}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: Biaya */}
          <tr>
            <td className="td-label">Biaya (Rp/kg)</td>
            {candidates.map(c => {
              const p = c.prediction;
              const val = p?.COST_IDR_PER_KG ?? 0;
              const ok = val <= specs.COST_IDR_PER_KG_MAX;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{p ? numberId(val, 0) : '—'}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: Peluang stabil */}
          <tr>
            <td className="td-label">Peluang stabil</td>
            {candidates.map(c => {
              const p = c.prediction;
              const val = p?.P_STABLE ?? 0;
              const ok = val >= 0.5;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  <span className={ok ? '' : 'miss'}>{p ? percentId(val) : '—'}</span>
                </td>
              );
            })}
          </tr>

          {/* Row: Ketidakpastian */}
          <tr>
            <td className="td-label">Ketidakpastian</td>
            {candidates.map(c => {
              const p = c.prediction;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  {p ? numberId(p.UNCERTAINTY, 2) : '—'}
                </td>
              );
            })}
          </tr>

          {/* Row: Bukti pasar */}
          <tr>
            <td className="td-label">Bukti pasar</td>
            {candidates.map(c => {
              const m = c.evidence.find(e => e.type === 'market');
              const d = m?.detail as { n_products_all?: number } | undefined;
              const count = d?.n_products_all ?? 0;
              return (
                <td key={c.candidate_id} className={`td-val ${c.candidate_id === selectedId ? 'td-selected' : ''}`}>
                  {count > 0 ? (
                    <span>{numberId(count, 0)} produk</span>
                  ) : (
                    <span style={{ color: 'var(--status-blocked-ink)', fontStyle: 'italic' }}>belum ditemukan</span>
                  )}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- Prediction Range Bars
function IntervalBar({ label, value, lo, hi, specLo, specHi, domain, log = false, format, prob }: {
  label: string; value: number; lo: number; hi: number; specLo: number; specHi: number; domain: [number, number];
  log?: boolean; format: (v: number) => string; prob?: number;
}) {
  const t = (v: number) => (log ? Math.log10(Math.max(v, 1e-9)) : v);
  const pos = (v: number) => Math.min(100, Math.max(0, ((t(v) - t(domain[0])) / (t(domain[1]) - t(domain[0]))) * 100));
  const ok = value >= specLo && value <= specHi;
  const specLeft = pos(specLo);
  const specWidth = Math.max(pos(specHi) - specLeft, 2);
  const ciLeft = pos(lo);
  const ciWidth = Math.max(pos(hi) - ciLeft, 2);

  return (
    <div className="pbar">
      <div className="pbar-head">
        <span className="pbar-label">{label}</span>
        <span className="pbar-value">
          {format(value)}
          {prob != null && <em className={prob >= 0.5 ? 'met' : 'miss'}> · peluang {prob >= 0.99 ? '≥ 99%' : percentId(prob)}</em>}
        </span>
      </div>
      <div className="pbar-track" role="img" aria-label={`${label}: ${format(value)}`}>
        <span className="pbar-spec" style={{ left: `${specLeft}%`, width: `${specWidth}%` }} />
        <span className="pbar-ci" style={{ left: `${ciLeft}%`, width: `${ciWidth}%` }} />
        <span className={'pbar-dot ' + (ok ? 'dot-ok' : 'dot-miss')} style={{ left: `${pos(value)}%` }} />
      </div>
      <div className="pbar-foot">
        <span>Rentang 95%: {format(lo)}–{format(hi)}</span>
        <span>target {format(specLo)}–{format(specHi)}</span>
      </div>
    </div>
  );
}

function PredictionBarsDetail({ candidate, specs }: { candidate: Candidate; specs: Specs }) {
  const p = candidate.prediction;
  if (!p) return <p className="muted small">Prediksi belum tersedia.</p>;
  const [vlo, vhi] = p.VISCOSITY_CP_CI95;
  const [plo, phi] = p.PH_CI95;
  const [dlo, dhi] = p.D50_UM_CI95;
  const ps = p.P_SPECS ?? {};

  return (
    <div className="prediction-bars-detail">
      <div className="prediction-bars-head">
        <span className="eyebrow" style={{ margin: 0 }}>
          PREDIKSI MODEL {p.model_version.toUpperCase()} · RENTANG 95%
        </span>
      </div>

      <IntervalBar
        label="Viskositas (cP, log)"
        value={p.VISCOSITY_CP}
        lo={vlo}
        hi={vhi}
        specLo={specs.VISCOSITY_CP[0]}
        specHi={specs.VISCOSITY_CP[1]}
        domain={[Math.min(specs.VISCOSITY_CP[0], vlo) / 2, Math.max(specs.VISCOSITY_CP[1], vhi) * 2]}
        log
        format={v => `${numberId(v, 0)} cP`}
        prob={ps.P_VISC}
      />
      <IntervalBar
        label="pH"
        value={p.PH}
        lo={plo}
        hi={phi}
        specLo={specs.PH[0]}
        specHi={specs.PH[1]}
        domain={[Math.min(specs.PH[0], plo) - 0.5, Math.max(specs.PH[1], phi) + 0.5]}
        format={v => numberId(v, 2)}
        prob={ps.P_PH}
      />
      <IntervalBar
        label="Droplet D50 (µm)"
        value={p.D50_UM}
        lo={dlo}
        hi={dhi}
        specLo={0}
        specHi={specs.D50_UM_MAX}
        domain={[0, Math.max(specs.D50_UM_MAX, dhi) * 1.3]}
        format={v => `${numberId(v, 2)} µm`}
        prob={ps.P_D50}
      />

      <div className="detail-mini-chips">
        <span className={`chip-pill ${p.P_STABLE >= 0.5 ? 'chip-met' : 'chip-miss'}`}>
          Peluang stabil {percentId(p.P_STABLE)}
        </span>
        <span className={`chip-pill ${candidate.formula.NIACINAMIDE >= specs.NIACINAMIDE_MIN_PCT ? 'chip-met' : 'chip-miss'}`}>
          Niacinamide {numberId(candidate.formula.NIACINAMIDE, 2)}% ({specTarget('NIACINAMIDE_MIN_PCT', specs)})
        </span>
        <span className={`chip-pill ${p.COST_IDR_PER_KG <= specs.COST_IDR_PER_KG_MAX ? 'chip-met' : 'chip-miss'}`}>
          Biaya {rupiah(p.COST_IDR_PER_KG)} ({specTarget('COST_IDR_PER_KG_MAX', specs)})
        </span>
        <span className="chip-pill chip-neutral">
          Ketidakpastian {numberId(p.UNCERTAINTY, 2)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Formula Table
function FormulaTable({ candidate, palette }: { candidate: Candidate; palette?: Palette }) {
  const byCode: Record<string, { code: string; inci: string; role: string }> = {};
  for (const item of palette?.ingredients ?? []) {
    byCode[item.code] = item;
  }
  const f = candidate.formula;
  const rows = INGREDIENTS.filter(code => f[code] > 0.0005);

  return (
    <div className="detail-formula-block">
      <h4 className="detail-section-title">FORMULA</h4>
      <table className="detail-formula-table">
        <thead>
          <tr>
            <th>Bahan (INCI)</th>
            <th>Peran</th>
            <th className="num">%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(code => (
            <tr key={code}>
              <td><strong>{byCode[code]?.inci ?? INCI_FALLBACK[code]}</strong></td>
              <td className="muted-cell">{byCode[code]?.role ?? 'active'}</td>
              <td className="num">{numberId(f[code], 2)}</td>
            </tr>
          ))}
          <tr className="aqua-row">
            <td>Aqua</td>
            <td className="muted-cell">pelarut (sisa)</td>
            <td className="num">{numberId(f.AQUA, 2)}</td>
          </tr>
        </tbody>
      </table>
      <div className="detail-process-line">
        <span>{numberId(f.RPM, 0)} rpm</span> · <span>{numberId(f.HMIN, 1)} menit</span> · <span>{numberId(f.TEMP, 0)} °C</span>
        {candidate.prediction && (
          <> · Biaya {rupiah(candidate.prediction.COST_IDR_PER_KG)}/kg <em className="asumsi-tag">harga asumsi</em></>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Guardian & Scout Detail Blocks
function GuardianChecksBlock({ issues }: { issues: Issue[] }) {
  const shown = issues.filter(i => i.code !== 'PENDING_CHECK');

  return (
    <div className="guardian-block">
      <h4 className="detail-section-title">PEMERIKSAAN GUARDIAN</h4>
      {shown.length === 0 ? (
        <div className="guardian-clean-note">
          <CheckCircle2 size={15} style={{ color: 'var(--status-pass-ink)' }} />
          <span>Seluruh batas regulasi BPOM dan persyaratan halal terpenuhi.</span>
        </div>
      ) : (
        <div className="guardian-issues-list">
          {shown.map((i, n) => (
            <div key={i.code + n} className={`guardian-warning-card issue-${i.severity}`}>
              <div className="warning-card-head">
                <AlertTriangle size={14} />
                <strong>PERINGATAN</strong>
                {['HALAL_SOURCE_CHECK', 'OVER_REG_MAX'].includes(i.code) && (
                  <span className="asumsi-badge">{ASSUMPTION_NOTE}</span>
                )}
              </div>
              <p className="warning-card-text">{i.message}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ScoutEvidenceBlock({ evidence }: { evidence: Evidence[] }) {
  const market = evidence.filter(e => e.type === 'market');
  const literature = evidence.filter(e => e.type === 'literature');

  return (
    <div className="scout-block">
      <h4 className="detail-section-title">BUKTI SCOUT</h4>
      <div className="scout-evidence-list">
        {market.map((e, n) => {
          const d = e.detail as { n_products_all?: number; n_indonesia?: number; weakest_pair?: string; min_pair_support?: number };
          const found = (d.n_products_all ?? 0) > 0;

          return (
            <div key={'m' + n} className="scout-market-card">
              <ShoppingBag size={15} style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <strong>
                  {found
                    ? `Kombinasi ditemukan di ${numberId(d.n_products_all, 0)} produk nyata`
                    : 'Kombinasi lengkap belum ditemukan di produk nyata'}
                </strong>
                {d.weakest_pair && (
                  <small style={{ display: 'block', color: 'var(--ink-muted)', marginTop: '2px' }}>
                    Pasangan bahan paling jarang: {pairLabel(d.weakest_pair)}, {numberId(d.min_pair_support, 0)} produk
                  </small>
                )}
                <small style={{ display: 'block', color: 'var(--ink-faint)', marginTop: '2px' }}>
                  Sumber: Open Beauty Facts (ODbL)
                </small>
              </div>
            </div>
          );
        })}

        {literature.map((e, n) => {
          const d = e.detail as { year?: number; journal?: string; url?: string; score?: number; pmcid?: string };
          return (
            <details key={'l' + n} className="scout-lit-card">
              <summary>
                <BookOpen size={14} style={{ flexShrink: 0 }} />
                <span>
                  <strong>{e.title}</strong>
                  <small>{[d.journal, d.year, d.pmcid].filter(Boolean).join(' · ')}{d.score != null ? ` · relevansi ${numberId(d.score, 2)}` : ''}</small>
                </span>
                <ChevronRight size={14} className="lit-chevron" />
              </summary>
              {d.url && (
                <div style={{ padding: '6px 0 0 24px' }}>
                  <a href={d.url} target="_blank" rel="noreferrer" className="lit-link">
                    Buka artikel di {e.source} <ExternalLink size={11} />
                  </a>
                </div>
              )}
            </details>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Formulator Decision & Lab
function FormulatorDecisionRow({ candidate, runDone }: { candidate: Candidate; runDone: boolean }) {
  const decide = useDecision();
  const [choice, setChoice] = useState<'approved' | 'rejected' | null>(null);
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState(false);
  const status = candidate.gate.status;
  const errors = candidate.gate.issues.filter(i => i.severity === 'error');
  const reasonOk = reason.trim().length >= 5;
  const canSubmit = choice !== null && reasonOk && !(choice === 'approved' && (status === 'blocked' || (status === 'review' && !ack)));

  return (
    <div className="formulator-decision-area">
      <h4 className="detail-section-title">KEPUTUSAN FORMULATOR</h4>
      {candidate.decision ? (
        <div className={`decision-done-badge decision-${candidate.decision}`}>
          {candidate.decision === 'approved' ? <Check size={14} /> : <X size={14} />}
          <span>{candidate.decision === 'approved' ? 'Disetujui' : 'Ditolak'}</span>
          {candidate.decision_reason && <span className="decision-reason-note">: "{candidate.decision_reason}"</span>}
        </div>
      ) : (
        <div className="decision-action-box">
          <div className="decision-btn-pair">
            <button
              className={`decision-pill-btn btn-approve ${choice === 'approved' ? 'active' : ''}`}
              disabled={status === 'blocked' || !runDone}
              onClick={() => setChoice('approved')}
            >
              <Check size={14} /> Setujui
            </button>
            <button
              className={`decision-pill-btn btn-reject ${choice === 'rejected' ? 'active' : ''}`}
              disabled={!runDone}
              onClick={() => setChoice('rejected')}
            >
              <X size={14} /> Tolak
            </button>
          </div>

          {status === 'blocked' && (
            <p className="inline-error small">Persetujuan dinonaktifkan: {errors.map(e => e.message).join(' ')}</p>
          )}

          {choice && (
            <div className="decision-reason-panel">
              <input
                type="text"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Alasan keputusan (minimal 5 karakter)"
                className="decision-reason-input"
              />
              {choice === 'approved' && status === 'review' && (
                <label className="check small">
                  <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />
                  Saya sudah membaca catatan review
                </label>
              )}
              <button
                className="primary-button"
                disabled={!canSubmit || decide.isPending}
                onClick={() => choice && decide.mutate({ id: candidate.candidate_id, body: { decision: choice, reason: reason.trim(), acknowledged: ack } })}
              >
                {decide.isPending ? 'Menyimpan…' : 'Simpan Keputusan'}
              </button>
            </div>
          )}
          {decide.error && <p className="inline-error small">{decide.error.message}</p>}
        </div>
      )}
    </div>
  );
}

function LabResultPanel({ result, candidate, specs }: { result: LabResult; candidate: Candidate; specs: Specs }) {
  const p = candidate.prediction;
  const o = result.outputs;
  const rows: [string, string, string][] = [
    ['NIACINAMIDE_MIN_PCT', `${numberId(candidate.formula.NIACINAMIDE, 2)}%`, `${numberId(candidate.formula.NIACINAMIDE, 2)}%`],
    ['VISCOSITY_CP', p ? numberId(p.VISCOSITY_CP, 0) : '—', numberId(o.VISCOSITY_CP, 0)],
    ['PH', p ? numberId(p.PH, 2) : '—', numberId(o.PH, 2)],
    ['D50_UM_MAX', p ? numberId(p.D50_UM, 2) : '—', numberId(o.D50_UM, 2)],
    ['STABLE', p ? `peluang ${percentId(p.P_STABLE)}` : '—', o.STABLE ? 'stabil' : 'tidak stabil'],
    ['COST_IDR_PER_KG_MAX', p ? rupiah(p.COST_IDR_PER_KG) : '—', rupiah(o.COST_IDR_PER_KG)],
  ];
  const met = SPEC_ORDER.filter(k => result.specs_met[k]).length;

  return (
    <div className={'lab-panel ' + (result.specs_met.ALL ? 'lab-hit' : 'lab-miss')}>
      <div className="lab-head">
        <span className="lab-badge">
          {result.source === 'virtual_lab' ? '🔬 Hasil Virtual Lab Emulsi' : result.source === 'historical' ? '📜 Data Historis' : 'Input Manual'} · Batch ke-{result.batch_index}
        </span>
        <strong>{met}/6 Spesifikasi Terpenuhi{result.specs_met.ALL ? ' — TARGET TERCAPAI' : ''}</strong>
      </div>
      <table>
        <thead>
          <tr><th>Parameter</th><th>Target</th><th className="num">Prediksi</th><th className="num">Hasil</th><th /></tr>
        </thead>
        <tbody>
          {rows.map(([k, pred, res]) => (
            <tr key={k}>
              <td>{SPEC_LABEL[k]}</td>
              <td>{specTarget(k, specs)}</td>
              <td className="num">{pred}</td>
              <td className="num">{res}</td>
              <td style={{ textAlign: 'center' }}>
                {result.specs_met[k] ? <Check size={15} className="met" /> : <X size={15} className="miss" />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.retrained_model_version && <small>Model diperbarui ke <b>{result.retrained_model_version}</b></small>}
    </div>
  );
}

// ---------------------------------------------------------------- Full Detail View of Selected Candidate
export function CandidateDetailView({
  candidate,
  specs,
  palette,
  runDone,
}: {
  candidate: Candidate;
  specs: Specs;
  palette?: Palette;
  runDone: boolean;
}) {
  const test = useTestCandidate();
  const reveal = useRevealCandidate();
  const isPool = candidate.origin === 'pool';
  const action = isPool ? reveal : test;
  const p = candidate.prediction;

  return (
    <article className="candidate-detail-container">
      {/* Detail Header */}
      <header className="detail-head">
        <div>
          <span className="detail-rank-tag">KANDIDAT #{candidate.rank}</span>
          <h3 className="detail-title">
            {isPool ? 'Formula dari data historis' : 'Formula usulan Designer'}
          </h3>
        </div>
        <GateBadge status={candidate.gate.status} />
      </header>

      {/* Main Prediction & Range Bars Banner */}
      <div className="detail-prediction-banner">
        <div className="detail-target-col">
          <span className="detail-target-percent">{p ? percentId(p.P_TARGET) : '—'}</span>
          <strong className="detail-target-text">Peluang memenuhi seluruh spesifikasi</strong>
          <small className="detail-target-model">Prediksi model {p?.model_version ?? 'gp-global-v1'}</small>
          {p && p.P_TARGET >= 0.94 && (
            <div className="model-rigor-note">
              *Batas atas 95%: memodelkan 5% batas noise pengukuran lab fisik
            </div>
          )}
        </div>

        <div className="detail-bars-col">
          <PredictionBarsDetail candidate={candidate} specs={specs} />
        </div>
      </div>

      {/* Two Columns: Formula on Left, Guardian/Scout on Right */}
      <div className="detail-two-columns">
        <div className="detail-left-col">
          <FormulaTable candidate={candidate} palette={palette} />
        </div>

        <div className="detail-right-col">
          <GuardianChecksBlock issues={candidate.gate.issues} />
          <ScoutEvidenceBlock evidence={candidate.evidence} />

          {candidate.summary.text && (
            <div className="detail-summary-card">
              <p className="summary-text-main">{candidate.summary.text}</p>
              <span className="summary-source-tag">
                {SUMMARY_SOURCE_LABEL[candidate.summary.source] ?? candidate.summary.source}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Formulator Decision & Lab Actions */}
      <footer className="detail-footer-actions">
        <FormulatorDecisionRow candidate={candidate} runDone={runDone} />

        {candidate.decision === 'approved' && !candidate.lab_result && (
          <button
            className="primary-button wide"
            style={{ marginTop: '14px' }}
            disabled={action.isPending}
            onClick={() => action.mutate(candidate.candidate_id)}
          >
            {isPool ? <History size={15} /> : <FlaskConical size={15} />}
            {action.isPending ? 'Mensimulasikan di Lab…' : isPool ? 'Ungkap Hasil Historis' : 'Uji di Virtual Lab'}
          </button>
        )}

        {action.error && <p className="inline-error small">{action.error.message}</p>}
        {candidate.lab_result && <LabResultPanel result={candidate.lab_result} candidate={candidate} specs={specs} />}
      </footer>
    </article>
  );
}

// ---------------------------------------------------------------- Master Section with [ Kartu | Tabel ]
export function CandidatesComparisonSection({
  candidates,
  specs,
  palette,
  runDone,
}: {
  candidates: Candidate[];
  specs: Specs;
  palette?: Palette;
  runDone: boolean;
}) {
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [selectedId, setSelectedId] = useState<string>(candidates[0]?.candidate_id ?? '');

  const activeId = candidates.some(c => c.candidate_id === selectedId)
    ? selectedId
    : (candidates[0]?.candidate_id ?? '');

  const selectedCandidate = candidates.find(c => c.candidate_id === activeId) ?? candidates[0];

  if (!candidates.length) return null;

  return (
    <section className="candidates-compare-section">
      {/* Top Header Row with Title and View Switcher */}
      <div className="compare-section-head">
        <h3 className="compare-title">Bandingkan kandidat</h3>
        <div className="compare-view-toggle">
          <button
            className={`toggle-btn ${viewMode === 'cards' ? 'active' : ''}`}
            onClick={() => setViewMode('cards')}
          >
            Kartu
          </button>
          <button
            className={`toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => setViewMode('table')}
          >
            Tabel
          </button>
        </div>
      </div>

      {/* Top View: Either Cards Grid or Comparison Table Matrix */}
      {viewMode === 'cards' ? (
        <div className="compact-cards-grid">
          {candidates.map(c => (
            <CandidateCompactCard
              key={c.candidate_id}
              candidate={c}
              specs={specs}
              isSelected={c.candidate_id === activeId}
              onSelect={() => setSelectedId(c.candidate_id)}
            />
          ))}
        </div>
      ) : (
        <CandidateComparisonTable
          candidates={candidates}
          specs={specs}
          selectedId={activeId}
          onSelect={setSelectedId}
        />
      )}

      {/* Bottom View: Selected Candidate Detailed Breakdown */}
      {selectedCandidate && (
        <CandidateDetailView
          candidate={selectedCandidate}
          specs={specs}
          palette={palette}
          runDone={runDone}
        />
      )}
    </section>
  );
}

// Backwards-compatible single CandidateCard export if needed
export function CandidateCard({
  candidate,
  runDone,
  specs,
  palette,
}: {
  candidate: Candidate;
  runDone: boolean;
  specs: Specs;
  palette?: Palette;
}) {
  return (
    <CandidateDetailView
      candidate={candidate}
      specs={specs}
      palette={palette}
      runDone={runDone}
    />
  );
}
