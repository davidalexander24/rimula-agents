import type { Specs } from '../api/types';

export const numberId = (v: number | null | undefined, digits = 1) =>
  v == null || !Number.isFinite(v) ? '—' : new Intl.NumberFormat('id-ID', { maximumFractionDigits: digits }).format(v);
export const percentId = (v: number | null | undefined, digits = 0) => (v == null || !Number.isFinite(v) ? '—' : `${numberId(v * 100, digits)}%`);
export const rupiah = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : `Rp ${numberId(v, 0)}`);
export const seconds = (ms: number | null | undefined) => (ms == null ? '' : ms < 1000 ? `${numberId(ms, 0)} md` : `${numberId(ms / 1000, 1)} dtk`);
export const timeId = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(iso)) : '—';
export const dateTimeId = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso)) : '—';

// Copy wajib PRD §15.5
export const GATE_LABEL: Record<string, string> = { pass: 'Lolos pemeriksaan', review: 'Perlu ditinjau', blocked: 'Diblokir' };
export const labelStatus = (s: string) =>
  ({ ...GATE_LABEL, running: 'Berjalan', done: 'Selesai', failed: 'Gagal' } as Record<string, string>)[s] ?? s;
export const SUMMARY_SOURCE_LABEL: Record<string, string> = {
  llm: 'Ringkasan orchestrator (Qwen3 lokal)',
  template: 'Ringkasan otomatis',
  unavailable: 'Ringkasan belum tersedia',
};
export const ASSUMPTION_NOTE = 'Asumsi tim — perlu verifikasi';

export const INGREDIENTS = ['GLYCERIN', 'NIACINAMIDE', 'CETEARYL_ALCOHOL', 'EMULSIFIER', 'CCT', 'DIMETHICONE', 'XANTHAN', 'CARBOMER', 'NAOH', 'PHENOXYETHANOL'] as const;
export const INCI_FALLBACK: Record<string, string> = {
  GLYCERIN: 'Glycerin', NIACINAMIDE: 'Niacinamide', CETEARYL_ALCOHOL: 'Cetearyl Alcohol', EMULSIFIER: 'Glyceryl Stearate (and) PEG-100 Stearate',
  CCT: 'Caprylic/Capric Triglyceride', DIMETHICONE: 'Dimethicone', XANTHAN: 'Xanthan Gum', CARBOMER: 'Carbomer',
  NAOH: 'Sodium Hydroxide (10%)', PHENOXYETHANOL: 'Phenoxyethanol', AQUA: 'Aqua',
};
export const pairLabel = (pair: unknown) => (typeof pair === 'string' ? pair.split('|').map(c => INCI_FALLBACK[c] ?? c).join(' + ') : '—');

export const SPEC_ORDER = ['NIACINAMIDE_MIN_PCT', 'VISCOSITY_CP', 'PH', 'D50_UM_MAX', 'STABLE', 'COST_IDR_PER_KG_MAX'] as const;
export const SPEC_LABEL: Record<string, string> = {
  NIACINAMIDE_MIN_PCT: 'Niacinamide', VISCOSITY_CP: 'Viskositas', PH: 'pH', D50_UM_MAX: 'Droplet D50',
  STABLE: 'Stabil', COST_IDR_PER_KG_MAX: 'Biaya bahan', ALL: 'Semua spesifikasi',
};
export function specTarget(key: string, specs?: Specs | null): string {
  if (!specs) return '—';
  switch (key) {
    case 'NIACINAMIDE_MIN_PCT': return `≥ ${numberId(specs.NIACINAMIDE_MIN_PCT)}%`;
    case 'VISCOSITY_CP': return `${numberId(specs.VISCOSITY_CP[0], 0)}–${numberId(specs.VISCOSITY_CP[1], 0)} cP`;
    case 'PH': return `${numberId(specs.PH[0], 2)}–${numberId(specs.PH[1], 2)}`;
    case 'D50_UM_MAX': return `≤ ${numberId(specs.D50_UM_MAX, 2)} µm`;
    case 'STABLE': return specs.STABLE ? 'stabil' : 'bebas';
    case 'COST_IDR_PER_KG_MAX': return `≤ ${rupiah(specs.COST_IDR_PER_KG_MAX)}/kg`;
    default: return '—';
  }
}

export const AGENT_LABEL: Record<string, string> = {
  orchestrator: 'Orchestrator', designer: 'Designer', guardian: 'Guardian', scout: 'Scout', lab: 'Virtual Lab', system: 'Sistem',
};
export const ACTION_LABEL: Record<string, string> = {
  run_started: 'Run dimulai', run_finished: 'Run selesai', llm_step: 'Langkah penalaran', propose: 'Usulkan kandidat',
  explain: 'Jelaskan prediksi', check: 'Periksa formula', literature: 'Cari literatur', market: 'Cek produk nyata',
  summarize: 'Susun ringkasan', lab_batch: 'Uji Virtual Lab', retrain: 'Perbarui model', policy_enforced: 'Kebijakan dijalankan',
  policy_override: 'Parameter disesuaikan', fallback_template: 'Pakai ringkasan otomatis', summary_rejected_number: 'Ringkasan ditolak (angka)',
  summary_rejected_claim: 'Ringkasan ditolak (klaim)', error: 'Galat',
};
