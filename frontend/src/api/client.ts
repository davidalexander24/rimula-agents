import type { Envelope, Health, SystemMode, Brief, Palette, RunCreate, RunCreated, Run, DecisionRequest, Candidate, LabTestResponse, Progress, ProgressResetRequest, ReplaySessionCreate, ReplaySession, EvaluationReport, ModelVersion, AgentsStatus, JobCreated } from './types';

export const API = 'api/v1';
export class ApiClientError extends Error {
  constructor(message: string, public readonly code: string, public readonly status: number,
    public readonly requestId?: string, public readonly mode?: SystemMode) {
    super(message); this.name = 'ApiClientError';
  }
}
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<Envelope<T>> {
  if (!path || path.startsWith('/') || path.includes('://') || path.split(/[?#]/)[0].split('/').includes('..')) {
    throw new ApiClientError('Alamat API tidak valid.', 'INVALID_PATH', 0);
  }
  const controller = new AbortController();
  const cancel = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 10_000);
  try {
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(API + '/' + path, { ...options, headers, credentials: 'same-origin', signal: controller.signal });
    const requestId = response.headers.get('X-Request-ID') ?? undefined;
    let body: unknown;
    try { body = await response.json(); }
    catch { throw new ApiClientError('Respons server tidak terbaca. Periksa koneksi dan sesi Jupyter.', 'INVALID_RESPONSE', response.status, requestId); }
    if (!isObject(body) || (body.mode !== 'live' && body.mode !== 'degraded')) {
      throw new ApiClientError('Format respons server belum sesuai kontrak.', 'INVALID_ENVELOPE', response.status, requestId);
    }
    if ('error' in body) {
      const error = body.error;
      if (!isObject(error) || typeof error.code !== 'string' || typeof error.message !== 'string') {
        throw new ApiClientError('Format pesan kesalahan tidak terbaca.', 'INVALID_ENVELOPE', response.status, requestId, body.mode);
      }
      throw new ApiClientError(error.message, error.code, response.status,
        typeof error.request_id === 'string' ? error.request_id : requestId, body.mode);
    }
    if (!response.ok) throw new ApiClientError('Permintaan belum berhasil. Silakan coba lagi.', 'HTTP_ERROR', response.status, requestId, body.mode);
    if (!('data' in body)) throw new ApiClientError('Payload respons tidak ditemukan.', 'INVALID_ENVELOPE', response.status, requestId, body.mode);
    return { mode: body.mode, data: body.data as T };
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    if (options.signal?.aborted) throw error;
    throw new ApiClientError(timedOut ? 'Server belum merespons. Silakan coba lagi.' : 'Tidak dapat terhubung ke server. Periksa koneksi atau sesi Jupyter.',
      timedOut ? 'TIMEOUT' : 'NETWORK_ERROR', 0);
  } finally {
    clearTimeout(timer); options.signal?.removeEventListener('abort', cancel);
  }
}
export function parseHealth(value: unknown): Health {
  const flags = ['model_ready', 'llm_ready', 'scout_ready', 'market_ready', 'evaluation_ready', 'db_ready'];
  if (!isObject(value) || flags.some(key => typeof value[key] !== 'boolean')
    || typeof value.instance !== 'string' || typeof value.virtual_lab_variant !== 'string'
    || (value.model_version !== null && typeof value.model_version !== 'string')) {
    throw new ApiClientError('Data status sistem belum sesuai kontrak.', 'INVALID_HEALTH', 200);
  }
  return value as unknown as Health;
}
export async function getHealth(signal?: AbortSignal): Promise<Envelope<Health>> {
  const result = await apiRequest<unknown>('health', { signal });
  return { mode: result.mode, data: parseHealth(result.data) };
}

const json = (body: unknown) => JSON.stringify(body);
export const getBriefs = () => apiRequest<Brief[]>('briefs');
export const getPalette = () => apiRequest<Palette>('palette');
export const createRun = (body: RunCreate) => apiRequest<RunCreated>('runs', { method: 'POST', body: json(body) });
export const getRun = (id: string, afterSeq = 0) => apiRequest<Run>(`runs/${encodeURIComponent(id)}?after_seq=${afterSeq}`);
export const decideCandidate = (id: string, body: DecisionRequest) => apiRequest<Candidate>(`candidates/${encodeURIComponent(id)}/decision`, { method: 'POST', body: json(body) });
export const testCandidate = (id: string) => apiRequest<LabTestResponse>(`candidates/${encodeURIComponent(id)}/test`, { method: 'POST' });
export const getProgress = (scope = 'global') => apiRequest<Progress>(`progress?scope=${encodeURIComponent(scope)}`);
export const resetProgress = (body: ProgressResetRequest = { scope: 'global' }) => apiRequest<Progress>('progress/reset', { method: 'POST', body: json(body) });
export const createReplaySession = (body: ReplaySessionCreate) => apiRequest<ReplaySession>('replay/sessions', { method: 'POST', body: json(body) });
export const getReplaySession = (id: string) => apiRequest<ReplaySession>(`replay/sessions/${encodeURIComponent(id)}`);
export const revealCandidate = (id: string) => apiRequest<LabTestResponse>(`candidates/${encodeURIComponent(id)}/reveal`, { method: 'POST' });
export const getEvaluation = () => apiRequest<EvaluationReport>('evaluation');
export const getModels = (scope?: string) => apiRequest<ModelVersion[]>(`models${scope ? `?scope=${encodeURIComponent(scope)}` : ''}`);
export const getAgentsStatus = () => apiRequest<AgentsStatus>('agents/status');
export const runAgent = (agent: string) => apiRequest<JobCreated>(`agents/${encodeURIComponent(agent)}/run`, { method: 'POST' });
export const getMarketSummary = () => apiRequest<Record<string, unknown>>('market/summary');
