import { QueryClientProvider } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { GUEST, configQuery, createQueryClient, meQuery } from '../api/queries';
import type { PublicConfig, Viewer } from '../api/queries';

// A query client that already holds /config and /auth/me (R2b), so a whole page renders without a request; tests
// block fetch. /config stays fresh for five minutes and /auth/me for good.
export function seededQueryClient({
  viewer = GUEST,
  config = { answer_feedback_enabled: false, login_available: true },
}: { viewer?: Viewer; config?: PublicConfig } = {}): QueryClient {
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, config);
  client.setQueryData(meQuery.queryKey, viewer);
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
