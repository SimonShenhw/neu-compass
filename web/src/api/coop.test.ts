import { describe, expect, it } from 'vitest';
import guest from '../fixtures/coop/list-guest.json';
import member1 from '../fixtures/coop/list-member-1.json';
import member2 from '../fixtures/coop/list-member-2.json';
import pending from '../fixtures/coop/upload-pending.json';
import { fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { ApiError } from './client';
import {
  coopListQuery,
  parseCoopList,
  parseUploadResponse,
  submitFailure,
  uploadCoop,
} from './coop';
import type { CoopUploadRequest } from './coop';
import { createQueryClient } from './queries';

const row = member2.body[0]!;
const unreadable = { status: 502, errorType: 'invalid_response' };
const request: CoopUploadRequest = {
  company: 'Example Co.',
  role: 'Data Co-op',
  coop_term: null,
  industry: 'startup',
  duration_months: 6,
  related_courses: ['CS 6140'],
  interview_summary: null,
  technical_questions: null,
  salary_range_usd: null,
};

describe('the Co-op list', () => {
  it('reads every fixture as it came', () => {
    for (const fixture of [guest, member1, member2])
      expect(parseCoopList(fixture.body)).toEqual(fixture.body);
  });

  it('keeps only the fields the page knows, and reads a missing nullable field as null', () => {
    const rest: Record<string, unknown> = { ...row, extra: 'x' };
    delete rest.coop_term;
    delete rest.salary_range_usd;
    const [parsed] = parseCoopList([rest]);
    expect(parsed).toEqual({ ...row, coop_term: null, salary_range_usd: null });
    expect(parsed).not.toHaveProperty('extra');
  });

  it.each([
    ['not a list', { ...row }],
    ['a row that is not an object', ['x']],
    ['no coop_id', [{ ...row, coop_id: undefined }]],
    ['an empty coop_id', [{ ...row, coop_id: '' }]],
    ['a company that is not text', [{ ...row, company: 1 }]],
    ['no role', [{ ...row, role: undefined }]],
    ['an industry the API does not have', [{ ...row, industry: 'fintech' }]],
    ['an industry that is not text', [{ ...row, industry: 3 }]],
    ['a duration of 0', [{ ...row, duration_months: 0 }]],
    ['a duration of 9', [{ ...row, duration_months: 9 }]],
    ['a duration that is not whole', [{ ...row, duration_months: 2.5 }]],
    ['a duration as text', [{ ...row, duration_months: '6' }]],
    ['courses that are not a list', [{ ...row, related_courses: 'CS 6140' }]],
    [
      'a course that is not text',
      [{ ...row, related_courses: ['CS 6140', 5] }],
    ],
    ['a term that is not text', [{ ...row, coop_term: 2025 }]],
    ['an interview that is not text', [{ ...row, interview_summary: {} }]],
    ['questions that are not text', [{ ...row, technical_questions: [] }]],
    ['a salary that is not text', [{ ...row, salary_range_usd: 45 }]],
    ['a level of 3', [{ ...row, visibility_level: 3 }]],
    ['a level as text', [{ ...row, visibility_level: '2' }]],
    ['no level', [{ ...row, visibility_level: undefined }]],
    ['one bad row among good ones', [...guest.body, { ...row, role: null }]],
  ])('%s makes the whole answer unreadable', (_name, value) => {
    expect(() => parseCoopList(value)).toThrow(ApiError);
    try {
      parseCoopList(value);
    } catch (error) {
      expect(error).toMatchObject(unreadable);
    }
  });

  it.each([1, 8, null])('a duration of %s is fine', (duration) => {
    expect(
      parseCoopList([{ ...row, duration_months: duration }])[0]!
        .duration_months,
    ).toBe(duration);
  });

  it('is kept under who is asking, and every visit asks again', () => {
    const query = coopListQuery('member:u-1:2');
    expect(query.queryKey).toEqual(['viewer', 'member:u-1:2', 'coop']);
    expect(query.staleTime).toBe(0);
  });

  it('is asked for with GET /coop and waits 30 seconds', async () => {
    const api = fakeApi(() => json(guest.body));
    expect(
      await createQueryClient().fetchQuery(coopListQuery('guest')),
    ).toEqual(guest.body);
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      'GET /coop',
    ]);
    await expectTimeout(
      () => createQueryClient().fetchQuery(coopListQuery('guest')),
      'slow',
    );
  });
});

describe('an upload', () => {
  it('reads the 201 with only the fields the page knows', () => {
    expect(parseUploadResponse({ ...pending.body, extra: 'x' })).toEqual(
      pending.body,
    );
  });

  it.each([
    ['not an object', []],
    ['no coop_id', { ...pending.body, coop_id: undefined }],
    ['an empty coop_id', { ...pending.body, coop_id: '' }],
    ['accepted as text', { ...pending.body, accepted: 'true' }],
    ['a level that is not whole', { ...pending.body, visibility_level: 1.5 }],
    ['an unknown status', { ...pending.body, status: 'queued' }],
    ['duplicate as a number', { ...pending.body, duplicate: 0 }],
    ['credited missing', { ...pending.body, contribution_credited: undefined }],
    ['a negative count', { ...pending.body, contribution_count: -1 }],
    ['a count that is not whole', { ...pending.body, contribution_count: 1.5 }],
    ['a count as text', { ...pending.body, contribution_count: '2' }],
  ])('with %s is unreadable', (_name, value) => {
    expect(() => parseUploadResponse(value)).toThrow(ApiError);
  });

  it.each(['pending', 'approved', 'rejected', 'published'])(
    'may be %s',
    (status) => {
      expect(parseUploadResponse({ ...pending.body, status }).status).toBe(
        status,
      );
    },
  );

  it('posts the request as it is to /coop, waits 30 seconds, and is sent once', async () => {
    const api = fakeApi(() => json(pending.body, 201));
    expect(await uploadCoop(request)).toEqual(pending.body);
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]).toMatchObject({
      method: 'POST',
      path: '/coop',
      body: request,
    });
    await expectTimeout(() => uploadCoop(request), 'slow');
  });

  it('whose 201 the page cannot read is an unreadable answer', async () => {
    fakeApi(() => json({ ...pending.body, status: 'queued' }, 201));
    await expect(uploadCoop(request)).rejects.toMatchObject(unreadable);
  });

  it('that failed tells the page the status, the error type and the refused fields, nothing else', () => {
    const error = new ApiError(422, {
      errorType: 'invalid_input',
      invalidFields: ['company'],
      retryAfter: 9,
      reason: 'x',
    });
    expect(submitFailure(error)).toEqual({
      ok: false,
      status: 422,
      errorType: 'invalid_input',
      invalidFields: ['company'],
    });
  });

  it('that failed with something not from the API reads as a lost connection', () => {
    expect(submitFailure(new Error('PRIVATE'))).toEqual({
      ok: false,
      status: 503,
      errorType: 'transport_error',
      invalidFields: [],
    });
  });
});
