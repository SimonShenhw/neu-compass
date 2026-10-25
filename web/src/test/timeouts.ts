import { expect, vi } from 'vitest';
import { ApiError, TIMEOUT_MS } from '../api/client';
import type { Timeout } from '../api/client';

// That `send` gives up after exactly the named timeout (R2b's four, R0 0.5): with a fetch that never answers it is
// still waiting a millisecond before, and settles at it, by default as a 504 transport_timeout (R5d).
export async function expectTimeout(
  send: () => Promise<unknown>,
  timeout: Timeout,
  check: (settled: unknown) => void = (settled) => {
    expect(settled).toBeInstanceOf(ApiError);
    expect(settled).toMatchObject({
      status: 504,
      errorType: 'transport_timeout',
    });
  },
) {
  vi.useFakeTimers();
  try {
    // This fetch stays for the rest of the test (later requests never answer either); the next test's setup puts the
    // blocking one back (test/setup.ts).
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_, reject) =>
            init.signal?.addEventListener('abort', () =>
              reject(init.signal?.reason),
            ),
          ),
      ),
    );
    const waiting = Symbol('waiting');
    let settled: unknown = waiting;
    void send().then(
      (value) => (settled = value),
      (error: unknown) => (settled = error),
    );
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS[timeout] - 1);
    expect(settled).toBe(waiting);
    await vi.advanceTimersByTimeAsync(1);
    check(settled);
  } finally {
    vi.useRealTimers();
  }
}
