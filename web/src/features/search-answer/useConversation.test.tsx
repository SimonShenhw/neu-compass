import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { ChatEvent, ChatSource } from '../../api/chat';
import { useConversation } from './useConversation';
import { INCOMPLETE } from '../../models/chatTurn';
import { searchFixture } from '../../fixtures/searchDemo';

const meta: ChatEvent = {
  type: 'meta',
  meta: { matched_via: 'alias', results: [] },
};
const failure = {
  status: 409,
  errorType: 'conflict',
  retryAfter: null,
  invalidFields: [],
  reason: 'plan_stale',
};
function source(events: ChatEvent[]): ChatSource {
  return async function* () {
    for (const event of events) yield event;
  };
}
function run(input: ChatSource) {
  const hook = renderHook(() => useConversation());
  act(() =>
    hook.result.current.ask({ question: 'q', allowSave: true, source: input }),
  );
  return hook;
}
it.each(['alias-cs-6140', 'model-error', 'daily-limit', 'feedback-receipt'])(
  'hook consumes real fixture events in order and settles %s',
  async (name) => {
    const hook = run(source(searchFixture(name).events));
    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    const last = hook.result.current.turns[0]!;
    expect(last.status).toBe(
      name === 'model-error' || name === 'daily-limit' ? 'stopped' : 'done',
    );
    expect(last.text).toBe(
      searchFixture(name)
        .events.filter((e) => e.type === 'token')
        .map((e) => e.text)
        .join(''),
    );
  },
);
it('hook classifies ChatFailure before the first event without leaking detail', async () => {
  const hook = run(async function* () {
    yield await Promise.reject({ ...failure, detail: 'private' });
  });
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
  expect(hook.result.current.turns[0]).toMatchObject({
    status: 'failed',
    failure,
    text: '',
    meta: null,
  });
});
it.each([new Error('private'), { status: 404 }, 'private'])(
  'hook normalizes unknown pre-event rejection %s',
  async (error) => {
    const hook = run(async function* () {
      yield await Promise.reject(error);
    });
    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(hook.result.current.turns[0]).toMatchObject({
      status: 'failed',
      failure: { status: 0 },
      error: null,
    });
  },
);
it('hook classifies post-event thrown failures as stopped, preserving the partial text', async () => {
  const hook = run(async function* () {
    yield meta;
    yield { type: 'token', text: 'partial' };
    throw failure;
  });
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
  expect(hook.result.current.turns[0]).toMatchObject({
    status: 'stopped',
    text: 'partial',
    error: { message: INCOMPLETE },
    failure: null,
  });
});
it.each(
  [[], [meta], [meta, { type: 'token', text: 'partial' }] as ChatEvent[]].map(
    (events) => ({ events }),
  ),
)(
  'hook marks an exhausted nonterminal source incomplete $events',
  async ({ events }) => {
    const hook = run(source(events));
    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(hook.result.current.turns[0]).toMatchObject({
      status: 'stopped',
      error: { message: INCOMPLETE },
    });
  },
);
it('hook synchronous busy lock refuses a second ask and permits the next settled turn', async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const started = vi.fn();
  const input: ChatSource = async function* () {
    started();
    await gate;
    yield meta;
    yield { type: 'done', feedback: null };
  };
  const hook = run(input);
  act(() =>
    hook.result.current.ask({
      question: 'ignored',
      allowSave: false,
      source: input,
    }),
  );
  expect(started).toHaveBeenCalledTimes(1);
  expect(hook.result.current.turns).toHaveLength(1);
  expect(hook.result.current.turns[0]!.status).toBe('waiting');
  await act(async () => {
    release();
  });
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
  act(() =>
    hook.result.current.ask({
      question: 'next',
      allowSave: false,
      source: source([meta, { type: 'done', feedback: null }]),
    }),
  );
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
  expect(
    hook.result.current.turns.map((t) => [t.id, t.question, t.allowSave]),
  ).toEqual([
    [1, 'q', true],
    [2, 'next', false],
  ]);
});
it('hook aborts on unmount and closes a noncooperative late source without reading later events', async () => {
  let release!: () => void, signal!: AbortSignal;
  const closed = vi.fn(),
    read = vi.fn();
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const hook = run(async function* (s) {
    signal = s;
    try {
      await gate;
      read('meta');
      yield meta;
      read('late');
      yield { type: 'token', text: 'late' };
    } finally {
      closed();
    }
  });
  hook.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => {
    release();
  });
  expect(read).toHaveBeenCalledExactlyOnceWith('meta');
  expect(closed).toHaveBeenCalledOnce();
});
it.each(['error', 'done'] as const)(
  'hook closes iteration at first terminal %s and ignores the tail',
  async (terminal) => {
    const tail = vi.fn();
    const closed = vi.fn();
    const hook = run(async function* () {
      try {
        yield meta;
        yield terminal === 'done'
          ? { type: 'done', feedback: 'receipt' }
          : { type: 'error', errorType: 'x', message: 'failed' };
        tail();
        yield { type: 'token', text: 'late' };
      } finally {
        closed();
      }
    });
    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(tail).not.toHaveBeenCalled();
    expect(closed).toHaveBeenCalledOnce();
    expect(hook.result.current.turns[0]!.text).toBe('');
  },
);
