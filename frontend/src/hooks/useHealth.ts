import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/client';
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: ({ signal }) => getHealth(signal), refetchInterval: 15_000, staleTime: 10_000, retry: 1 });
}
