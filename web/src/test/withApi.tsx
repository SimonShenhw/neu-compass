import { QueryClientProvider } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { GUEST, configQuery, createQueryClient, meQuery } from '../api/queries';
import type { PublicConfig, Viewer } from '../api/queries';
import { readyQuery } from '../api/ready';

// The top bar's /ready in a seeded client: a synthetic count (R3e).
export const SEEDED_READY = {
  status: 'ready',
  courses_indexed: 4321,
  bm25_corpus: 4321,
};

// A query client that already holds /config, /auth/me (R2b) and the top bar's /ready (R3e), so a whole page renders
// without a request; tests block fetch. /config and /ready stay fresh for five minutes and /auth/me for good.
export function seededQueryClient({
  viewer = GUEST,
  config = { answer_feedback_enabled: false, login_available: true },
}: { viewer?: Viewer; config?: PublicConfig } = {}): QueryClient {
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, config);
  client.setQueryData(meQuery.queryKey, viewer);
  client.setQueryData(readyQuery.queryKey, SEEDED_READY);
  return client;
}

export function WithApi({
  children,
  client,
}: {
  children: ReactNode;
  client?: QueryClient;
}) {
  const [fallback] = useState(() => seededQueryClient());
  return (
    <QueryClientProvider client={client ?? fallback}>
      {children}
    </QueryClientProvider>
  );
}
