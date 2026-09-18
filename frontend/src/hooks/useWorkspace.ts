import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import { createReplaySession, createRun, decideCandidate, getAgentsStatus, getBriefs, getEvaluation, getMarketSummary, getModels, getPalette, getProgress, getReplaySession, getRun, resetProgress, revealCandidate, runAgent, testCandidate } from '../api/client';
import type { AgentEvent, DecisionRequest, EvaluationReport, RunCreate } from '../api/types';

export const useBriefs = () => useQuery({ queryKey: ['briefs'], queryFn: getBriefs, staleTime: 60_000 });
export const usePalette = () => useQuery({ queryKey: ['palette'], queryFn: getPalette, staleTime: 300_000, retry: false });
export const useProgress = (scope = 'global', enabled = true) =>
  useQuery({ queryKey: ['progress', scope], queryFn: () => getProgress(scope), enabled, refetchInterval: 3_000, refetchIntervalInBackground: true });

export const useEvaluation = () => useQuery({
  queryKey: ['evaluation'],
  queryFn: async () => {
    try {
      return { ...(await getEvaluation()), fixture: false };
    } catch (error) {
      // PRD §15.2: fixture hanya jika GET /evaluation 404, dengan banner "DATA CONTOH".
      if (error instanceof Error && 'status' in error && (error as { status?: number }).status === 404) {
        const response = await fetch('../contracts/fixtures/evaluation_min.json');
        if (response.ok) return { mode: 'degraded' as const, data: (await response.json()) as EvaluationReport, fixture: true };
      }
      throw error;
    }
  },
  retry: false,
  staleTime: 60_000,
});

export const useAgentsStatus = (fast = false) =>
  useQuery({ queryKey: ['agents'], queryFn: getAgentsStatus, retry: false, refetchInterval: fast ? 1_000 : 15_000 });
export const useMarketSummary = () => useQuery({ queryKey: ['market'], queryFn: getMarketSummary, retry: false, staleTime: 60_000 });
export const useModels = (scope?: string) => useQuery({ queryKey: ['models', scope], queryFn: () => getModels(scope), retry: false, staleTime: 5_000 });

/** Polling run tiap 1 dtk dengan after_seq; event dikumpulkan (API hanya mengirim seq > after_seq). */
export function useRun(runId?: string) {
  const state = useRef<{ id?: string; after: number; events: AgentEvent[] }>({ after: 0, events: [] });
  if (state.current.id !== runId) state.current = { id: runId, after: 0, events: [] };
  return useQuery({
    queryKey: ['run', runId],
    enabled: Boolean(runId),
    queryFn: async () => {
      const s = state.current;
      const result = await getRun(runId as string, s.after);
      const known = new Set(s.events.map(e => e.seq));
      const fresh = result.data.events.filter(e => !known.has(e.seq));
      if (fresh.length) {
        s.events = [...s.events, ...fresh].sort((a, b) => a.seq - b.seq);
        s.after = Math.max(s.after, ...fresh.map(e => e.seq));
      }
      return { ...result, data: { ...result.data, events: s.events } };
    },
    refetchInterval: q => (q.state.data?.data.status === 'running' ? 1000 : false),
    // Demo: presenter bisa pindah ke jendela slide saat run berjalan; polling jangan berhenti.
    refetchIntervalInBackground: true,
  });
}

export const useCreateRun = () => useMutation({ mutationFn: (body: RunCreate) => createRun(body) });

export const useDecision = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: DecisionRequest }) => decideCandidate(id, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['run'] }),
  });
};

const refreshAfterLab = (qc: ReturnType<typeof useQueryClient>) => {
  for (const key of ['run', 'progress', 'health', 'models', 'replay']) void qc.invalidateQueries({ queryKey: [key] });
};
export const useTestCandidate = () => { const qc = useQueryClient(); return useMutation({ mutationFn: testCandidate, onSuccess: () => refreshAfterLab(qc) }); };
export const useRevealCandidate = () => { const qc = useQueryClient(); return useMutation({ mutationFn: revealCandidate, onSuccess: () => refreshAfterLab(qc) }); };
export const useResetProgress = () => { const qc = useQueryClient(); return useMutation({ mutationFn: resetProgress, onSuccess: () => refreshAfterLab(qc) }); };

export const useCreateReplaySession = () => useMutation({ mutationFn: createReplaySession });
export const useReplaySession = (id?: string) =>
  useQuery({ queryKey: ['replay', id], enabled: Boolean(id), queryFn: () => getReplaySession(id as string), retry: false });

export const useRunAgent = () => {
  const qc = useQueryClient();
  return useMutation({ mutationFn: runAgent, onSuccess: () => { void qc.invalidateQueries({ queryKey: ['agents'] }); void qc.invalidateQueries({ queryKey: ['models'] }); } });
};
