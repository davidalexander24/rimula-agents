// Padanan fp/schemas.py — CONTRACT_VERSION 1.0. Ubah setelah kontrak David berubah.
export type SystemMode = 'live' | 'degraded';
export type GateStatus = 'pass' | 'review' | 'blocked';
export type Severity = 'error' | 'warning' | 'info';
export type RunMode = 'explore' | 'replay';
export type RunStatus = 'running' | 'done' | 'failed';
export type LlmStatus = 'not_used' | 'ok' | 'degraded';
export type EventStatus = 'started' | 'done' | 'failed';
export type Origin = 'explore' | 'pool';
export type Decision = 'approved' | 'rejected';
export type LabSource = 'virtual_lab' | 'historical' | 'manual';
export type SummarySource = 'llm' | 'template' | 'unavailable';
export type EvidenceType = 'literature' | 'market';
export type AgentName = 'orchestrator' | 'designer' | 'guardian' | 'scout' | 'lab' | 'system';
export type JobKind = 'designer_retrain' | 'scout_reindex' | 'guardian_recheck';
export type JobTrigger = 'manual' | 'schedule' | 'lab_result';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type Range = [number, number];
export interface Specs {
  NIACINAMIDE_MIN_PCT: number; VISCOSITY_CP: Range; PH: Range;
  D50_UM_MAX: number; STABLE: boolean; COST_IDR_PER_KG_MAX: number;
}
export interface Brief { brief_id: string; name: string; description: string; specs: Specs }
export interface Formula {
  GLYCERIN: number; NIACINAMIDE: number; CETEARYL_ALCOHOL: number; EMULSIFIER: number;
  CCT: number; DIMETHICONE: number; XANTHAN: number; CARBOMER: number;
  NAOH: number; PHENOXYETHANOL: number; AQUA: number; RPM: number; HMIN: number; TEMP: number;
}
export interface Prediction {
  VISCOSITY_CP: number; VISCOSITY_CP_CI95: Range; PH: number; PH_CI95: Range;
  D50_UM: number; D50_UM_CI95: Range; P_STABLE: number; COST_IDR_PER_KG: number;
  P_SPECS: Record<string, number>; P_TARGET: number; UNCERTAINTY: number; model_version: string;
}
export interface Issue { code: string; severity: Severity; message: string; field: string | null }
export interface Gate { status: GateStatus; issues: Issue[] }
export interface Evidence { type: EvidenceType; title: string; detail: Record<string, unknown>; source: string }
export interface Summary { text: string | null; source: SummarySource; reason: string | null }
export interface LabResult {
  lab_result_id: string; batch_index: number; outputs: Record<string, number>;
  specs_met: Record<string, boolean>; source: LabSource; variant: string | null;
  recorded_at: string; retrained_model_version: string | null;
}
export interface Candidate {
  candidate_id: string; run_id: string; rank: number; origin: Origin; source_record_id: string | null;
  formula: Formula; prediction: Prediction | null; gate: Gate; evidence: Evidence[];
  summary: Summary; decision: Decision | null; decision_reason: string | null;
  acknowledged: boolean; lab_result: LabResult | null;
}
export interface AgentEvent {
  seq: number; agent: string; action: string; status: EventStatus; detail: Record<string, unknown>;
  duration_ms: number | null; ts: string;
}
export interface Run {
  run_id: string; run_mode: RunMode; session_id: string | null; brief_id: string; specs: Specs;
  n: number; use_orchestrator: boolean; status: RunStatus; llm_status: LlmStatus;
  model_version: string; recommendation: string | null; error: string | null;
  created_at: string; finished_at: string | null; candidates: Candidate[]; events: AgentEvent[];
}
export interface ProgressSummary {
  scope: string; batches: number; hit_at_batch: number | null; best_specs_met: number; total_specs: number;
}
export interface BatchRecord { batch_index: number; candidate_id: string; specs_met: Record<string, boolean>; outputs: Record<string, number> }
export interface Progress extends ProgressSummary { history: BatchRecord[] }
export interface ApiError { code: string; message: string; request_id: string }
export interface Envelope<T> { mode: SystemMode; data: T }
export interface ErrorEnvelope { mode: SystemMode; error: ApiError }
export interface RunCreate { run_mode?: RunMode; brief_id: string; specs?: Specs | null; n?: number; use_orchestrator?: boolean; session_id?: string | null }
export interface RunCreated { run_id: string; status: RunStatus }
export interface RunListItem {
  run_id: string; run_mode: RunMode; session_id: string | null; brief_id: string; n: number;
  use_orchestrator: boolean; status: RunStatus; llm_status: LlmStatus; model_version: string;
  created_at: string; finished_at: string | null;
}
export interface DecisionRequest { decision: Decision; reason?: string; acknowledged?: boolean }
export interface LabTestResponse { candidate: Candidate; lab_result: LabResult; progress: Progress }
export interface ManualResultRequest { outputs: Record<string, number> }
export interface ReplaySessionCreate { brief_id: string; seed?: number | null }
export interface KnownRecord { record_id: string; formula: Formula; outputs: Record<string, number>; specs_met: Record<string, boolean> }
export interface ReplaySession {
  session_id: string; brief_id: string; seed: number | null; progress: Progress | null;
  known: KnownRecord[]; pool_size: number; model_version: string;
}
export interface ProgressResetRequest { scope?: 'global' }
export interface Health {
  model_ready: boolean; model_version: string | null; llm_ready: boolean; scout_ready: boolean;
  market_ready: boolean; evaluation_ready: boolean; db_ready: boolean; instance: string; virtual_lab_variant: string;
}
export interface PaletteIngredient { code: string; inci: string; role: string; min_pct: number; max_pct: number; price_idr_per_kg: number; notes: string | null }
export interface ProcessParam { code: string; label: string; unit: string; min: number; max: number }
export interface Palette { ingredients: PaletteIngredient[]; process: ProcessParam[] }
export interface ModelVersion { version: string; scope: string; n_train: number; parent_version: string | null; is_active: boolean; created_at: string }
export interface Job { job_id: string; kind: JobKind; trigger: JobTrigger; status: JobStatus; detail: Record<string, unknown>; started_at: string | null; finished_at: string | null }
export interface JobCreated { job_id: string }
export interface AgentStatus { ready: boolean; last_job: Job | null; next_run: string | null }
export interface AgentsStatus { designer: AgentStatus; guardian: AgentStatus; scout: AgentStatus; market: AgentStatus; scheduler: AgentStatus }
export interface EvaluationReport {
  generated_at: string; quick: boolean; brief_id: string; cv: Record<string, unknown>; unc_max: number | null;
  hit_rate_random: Record<string, number | null>; closed_loop: Record<string, unknown>;
  replay_historical: Record<string, unknown>; liposome_validation: Record<string, unknown>;
  savings_estimate: Record<string, unknown>; runtime_seconds: number | null; notes: string[];
  [key: string]: unknown;
}
