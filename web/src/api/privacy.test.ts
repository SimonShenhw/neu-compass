import { describe, expect, it } from 'vitest';
import deleted from '../fixtures/privacy/delete-ok.json';
import nothing from '../fixtures/privacy/delete-ok-nothing-else.json';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import { apiError, fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { deleteAccount, parseDeleteResult, privacyQuery } from './privacy';
import { PUBLIC_FRESH_MS, createQueryClient } from './queries';

describe('the deletion’s answer', () => {
  it('reads both fixtures, keeping only its own keys', () => {
    expect(parseDeleteResult(deleted.body)).toEqual(deleted.body);
    expect(parseDeleteResult(nothing.body)).toEqual(nothing.body);
    expect(parseDeleteResult({ ...deleted.body, extra: 1 })).toEqual(
      deleted.body,
    );
  });

  it.each([
    ['not an object', [deleted.body]],
    ['deleted false', { ...deleted.body, deleted: false }],
    ['deleted as text', { ...deleted.body, deleted: 'true' }],
    ...(
      [
        'published_experiences',
        'unlocks_of_those',
        'own_unlocks',
        'submissions',
        'credits',
        'planned_courses',
        'withdrawn_from_groups',
      ] as const
    ).flatMap((name) => [
      [`no ${name}`, { ...deleted.body, [name]: undefined }],
      [`a negative ${name}`, { ...deleted.body, [name]: -1 }],
      [`${name} not whole`, { ...deleted.body, [name]: 0.5 }],
      [`${name} as text`, { ...deleted.body, [name]: '1' }],
    ]),
  ] as [string, unknown][])('with %s is not read', (_name, value) => {
    expect(parseDeleteResult(value)).toBeNull();
  });
});

describe('deleting the account', () => {
  it('posts exactly {"confirm": "delete"} once and gives the result', async () => {
    const api = fakeApi(() => json(deleted.body));
    expect(await deleteAccount()).toEqual({ ok: true, result: deleted.body });
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]).toMatchObject({
      method: 'POST',
      path: '/auth/delete-account',
      body: { confirm: 'delete' },
    });
  });

  it.each([
    ['a 401', () => apiError(401, 'unauthorized', 'Unknown user.'), 401],
    ['a 403', () => apiError(403, 'csrf_rejected', 'refused'), 403],
    ['a 503', () => apiError(503, 'service_unavailable', 'down'), 503],
    [
      'a proxy’s page',
      () => new Response('<html></html>', { status: 502 }),
      502,
    ],
    ['a 200 it cannot read', () => json({ deleted: true }), 502],
    ['a 200 that is not JSON', () => new Response('ok'), 502],
    [
      'no connection',
      () => {
        throw new TypeError('Failed to fetch');
      },
      null,
    ],
  ])(
    'after %s says the status, or null for no answer',
    async (_name, answer, status) => {
      fakeApi(answer);
      expect(await deleteAccount()).toEqual({ ok: false, status });
    },
  );

  it('waits 15 seconds; no answer by then is no answer', async () => {
    await expectTimeout(deleteAccount, 'write', (settled) =>
      expect(settled).toEqual({ ok: false, status: null }),
    );
  });
});

describe('the privacy text', () => {
  it('is GET /privacy, the same for everyone and fresh for five minutes, waiting 8 seconds', async () => {
    expect(privacyQuery.queryKey).toEqual(['privacy']);
    expect(privacyQuery.staleTime).toBe(PUBLIC_FRESH_MS);
    const api = fakeApi(() => json(privacy.body));
    expect(await createQueryClient().fetchQuery(privacyQuery)).toEqual(
      privacy.body,
    );
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      'GET /privacy',
    ]);
    await expectTimeout(
      () => createQueryClient().fetchQuery(privacyQuery),
      'read',
    );
  });
});
