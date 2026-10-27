import { describe, expect, it } from 'vitest';
import type { DraftNode } from '../api/draft';
import {
  canRetryDraft,
  creditsText,
  draftFailureMessage,
  draftTreeLines,
  parseDraftAnswer,
} from './planDraft';
import {
  answerOf,
  failureVectors,
  treeVectors,
} from '../features/programs/draftTestUtils';
import { draftFixture } from '../fixtures/draftDemo';

type Json = Record<string, unknown>;
const at = (value: unknown, path: (string | number)[]) => {
  let cursor = value as Json;
  for (const key of path) cursor = cursor[key] as Json;
  return cursor;
};
// A real answer with every part filled (notices with candidates, a pool, unknown credits), edited in one place.
function edited(
  change: (answer: Json) => void,
  name = 'draft-standard-notices',
) {
  const answer = answerOf(name);
  change(answer);
  return parseDraftAnswer(answer).kind;
}
const root = (a: Json) => at(a, ['result', 'root']);
const leaf = (status: DraftNode['status'] = 'met'): DraftNode => ({
  kind: 'course',
  label: 'Synthetic leaf',
  status,
  reasons: [],
  reasons_omitted: 0,
  counted: [],
  possible: [],
  missing: [],
  missing_omitted: 0,
  shortfall: {},
  children: [],
});
const astral = (n: number) => '𝔸'.repeat(n); // One code point, two UTF-16 units each.

describe('real answers', () => {
  it.each([
    'draft-standard-empty',
    'draft-standard-add',
    'draft-standard-mixed',
    'draft-standard-notices',
    'draft-standard-invalid-many',
    'draft-standard-too-many',
    'draft-standard-all-present',
    'draft-standard-over-limit',
    'draft-standard-nothing-new',
    'draft-standard-full',
    'draft-standard-text-input',
    'draft-standard-records-changed',
    'draft-align-empty',
    'draft-align-mixed',
    'draft-older-add',
    'draft-ds-mixed',
    'draft-text-edge',
    'draft-other-revision',
  ])('%s is a readable answer', (name) => {
    expect(parseDraftAnswer(draftFixture(name).body).kind).toBe('ok');
  });
  it('the answer without its result is not', () => {
    expect(parseDraftAnswer(draftFixture('draft-malformed').body)).toEqual({
      kind: 'invalid',
    });
  });
  it('a readable answer comes back as it was sent', () => {
    const body = draftFixture('draft-standard-notices').body;
    const parsed = parseDraftAnswer(body);
    expect(parsed.kind === 'ok' && parsed.answer).toBe(body);
  });
});

describe('the answer as a whole (spec section 4)', () => {
  it.each([null, undefined, [], 'answer', 3, true])(
    '%s is not an answer',
    (v) => {
      expect(parseDraftAnswer(v).kind).toBe('invalid');
    },
  );
  it.each([
    ['uppercase hex', 'D'.repeat(64)],
    ['63 characters', 'd'.repeat(63)],
    ['65 characters', 'd'.repeat(65)],
    ['not hex', 'g'.repeat(64)],
    ['a number', 7],
    ['missing', undefined],
  ])('plan_content_sha256 %s', (_, value) => {
    expect(
      edited((a) => {
        if (value === undefined) delete a.plan_content_sha256;
        else a.plan_content_sha256 = value;
      }),
    ).toBe('invalid');
  });
});

describe('courses', () => {
  const course = (change: (c: Json) => void, index = 0) =>
    edited((a) => change(at(a, ['courses', index])), 'draft-standard-full');
  it('a full draft of 20 is fine, 21 is not', () => {
    expect(edited(() => {}, 'draft-standard-full')).toBe('ok');
    expect(
      edited((a) => {
        const list = a.courses as Json[];
        list.push({ ...list[0]!, code: 'ZZZ 9999', course_id: 'c-zz' });
      }, 'draft-standard-full'),
    ).toBe('invalid');
  });
  it.each([
    ['not a list', (a: Json) => (a.courses = {})],
    [
      'a row that is not an object',
      (a: Json) => ((a.courses as unknown[])[0] = 'CS 5010'),
    ],
    [
      'two rows with one code',
      (a: Json) => {
        const list = a.courses as Json[];
        list[1] = { ...list[1]!, code: list[0]!.code };
      },
    ],
  ])('%s', (_, change) => {
    expect(edited(change, 'draft-standard-full')).toBe('invalid');
  });
  it.each([
    ['', 'invalid'],
    ['c'.repeat(200), 'ok'],
    ['c'.repeat(201), 'invalid'],
    [astral(200), 'ok'],
    [astral(201), 'invalid'],
    [5010, 'invalid'],
  ])('a course_id of %j', (value, kind) => {
    expect(course((c) => (c.course_id = value))).toBe(kind);
  });
  // Course 7 of the full draft is ZZ 7002, which `added` does not name. The other codes here are unused but CS 5010,
  // course 0's code, which fails only as a repeat.
  it.each([
    ['AB 1234', 'ok'],
    ['EECE 5644', 'ok'],
    ['CS 5010A', 'ok'],
    ['CS 5010', 'invalid'],
    ['cs 5010', 'invalid'],
    ['C 5010', 'invalid'],
    ['ABCDE 5010', 'invalid'],
    ['CS 501', 'invalid'],
    ['CS 50100', 'invalid'],
    ['CS 5010AB', 'invalid'],
    ['CS 5011a', 'invalid'],
    ['CS-5010', 'invalid'],
    ['CS  5010', 'invalid'],
    ['CS\t5011', 'invalid'],
    ['CS 5011', 'invalid'],
    [' CS 5010', 'invalid'],
    ['CS 5010\n', 'invalid'],
    ['CS ５０１０', 'invalid'],
    ['CS ٥٠١٠', 'invalid'],
  ])('a course code of %j', (value, kind) => {
    expect(course((c) => (c.code = value), 7)).toBe(kind);
  });
  it.each([
    ['', 'invalid'],
    ['n'.repeat(500), 'ok'],
    ['n'.repeat(501), 'invalid'],
    [astral(500), 'ok'],
    [astral(501), 'invalid'],
    [null, 'invalid'],
  ])('a course name of %j', (value, kind) => {
    expect(course((c) => (c.name = value))).toBe(kind);
  });
  it.each([
    [0, 'ok'],
    [12, 'ok'],
    [null, 'ok'],
    [13, 'invalid'],
    [-1, 'invalid'],
    [4.5, 'invalid'],
    [true, 'invalid'],
    ['4', 'invalid'],
    [Number.NaN, 'invalid'],
  ])('credits of %j', (value, kind) => {
    expect(course((c) => (c.credits = value))).toBe(kind);
  });
  it('credits must be there, even as null', () => {
    expect(course((c) => delete c.credits)).toBe('invalid');
  });
});

describe('added', () => {
  it.each([
    ['not a list', (a: Json) => (a.added = 'CS 5800')],
    ['a code that is not a string', (a: Json) => (a.added = [5800])],
    [
      'the same code twice',
      (a: Json) => {
        const added = a.added as string[];
        added.push(added[0]!);
      },
    ],
    ['a code not in the draft', (a: Json) => (a.added = ['ZZZ 9999'])],
    ['missing', (a: Json) => delete a.added],
  ])('%s', (_, change) => {
    expect(edited(change, 'draft-standard-add')).toBe('invalid');
  });
  it('empty is fine', () => {
    expect(edited((a) => (a.added = []), 'draft-standard-add')).toBe('ok');
  });
});

describe('notices', () => {
  const ambiguous = (a: Json) =>
    (a.notices as Json[]).find((n) => (n.candidates as unknown[]).length > 0)!;
  it.each([
    ['not a list', (a: Json) => (a.notices = {})],
    [
      'a notice that is not an object',
      (a: Json) => ((a.notices as unknown[])[0] = 'x'),
    ],
    ['an unknown kind', (a: Json) => (at(a, ['notices', 0]).kind = 'other')],
    [
      'a kind from Object.prototype',
      (a: Json) => (at(a, ['notices', 0]).kind = 'constructor'),
    ],
    ['an unknown level', (a: Json) => (at(a, ['notices', 0]).level = 'error')],
    ['empty text', (a: Json) => (at(a, ['notices', 0]).text = '')],
    [
      'text that is not a string',
      (a: Json) => (at(a, ['notices', 0]).text = 1),
    ],
    [
      'candidates that are not a list',
      (a: Json) => (ambiguous(a).candidates = {}),
    ],
    [
      '11 candidates',
      (a: Json) => {
        const list = ambiguous(a).candidates as Json[];
        while (list.length < 11) list.push({ code: 'ZZ 0000', name: 'Z' });
      },
    ],
    [
      'a candidate without a name',
      (a: Json) => delete at(ambiguous(a), ['candidates', 0]).name,
    ],
    [
      'a candidate code that is not a string',
      (a: Json) => (at(ambiguous(a), ['candidates', 0]).code = 5010),
    ],
    [
      'a candidate name that is not a string',
      (a: Json) => (at(ambiguous(a), ['candidates', 0]).name = null),
    ],
    [
      'a candidate that is not an object',
      (a: Json) => ((ambiguous(a).candidates as unknown[])[0] = 'CS 5010'),
    ],
    [
      'a negative omitted count',
      (a: Json) => (ambiguous(a).candidates_omitted = -1),
    ],
    [
      'a fractional omitted count',
      (a: Json) => (ambiguous(a).candidates_omitted = 1.5),
    ],
    [
      'no omitted count',
      (a: Json) => delete at(a, ['notices', 0]).candidates_omitted,
    ],
  ])('%s', (_, change) => {
    expect(edited(change)).toBe('invalid');
  });
  it('notice text only has to be non-empty: spaces alone are fine', () => {
    expect(edited((a) => (at(a, ['notices', 0]).text = '  '))).toBe('ok');
  });
  it('exactly 10 candidates, with empty names, are fine', () => {
    expect(
      edited((a) => {
        const list = ambiguous(a).candidates as Json[];
        list.length = 0;
        for (let i = 0; i < 10; i++)
          list.push({ code: `ZZ 000${i}`, name: '' });
      }),
    ).toBe('ok');
  });
  it.each([
    'course_gone',
    'duplicate_code',
    'too_many_codes',
    'invalid_format',
    'invalid_format_more',
    'all_present',
    'over_limit',
    'not_found',
    'ambiguous',
    'cross_listed_twin',
    'also_matches',
    'primary_code',
    'invalid_record',
    'nothing_new',
  ])('a notice of kind %s is fine, at either level', (kind) => {
    for (const level of ['warning', 'info'])
      expect(
        edited((a) => Object.assign(at(a, ['notices', 0]), { kind, level })),
      ).toBe('ok');
  });
});

describe('result', () => {
  it.each([
    ['not an object', (a: Json) => (a.result = [])],
    ['null in place of the result', (a: Json) => (a.result = null)],
    ['no root', (a: Json) => delete at(a, ['result']).root],
    [
      '21 unplaced codes',
      (a: Json) => (at(a, ['result']).unplaced = Array(21).fill('ZZ 0000')),
    ],
    [
      'an unplaced code that is not a string',
      (a: Json) => (at(a, ['result']).unplaced = [1]),
    ],
    ['no unplaced list', (a: Json) => delete at(a, ['result']).unplaced],
    ['no counts', (a: Json) => delete at(a, ['result']).summary_counts],
    [
      'counts that are a list',
      (a: Json) => (at(a, ['result']).summary_counts = [0, 0, 0]),
    ],
    [
      'a negative count',
      (a: Json) => (at(a, ['result', 'summary_counts']).met = -1),
    ],
    [
      'a missing count',
      (a: Json) => delete at(a, ['result', 'summary_counts']).unknown,
    ],
    [
      'a count that is text',
      (a: Json) => (at(a, ['result', 'summary_counts']).missing = '0'),
    ],
  ])('%s', (_, change) => {
    expect(edited(change)).toBe('invalid');
  });
  it('20 unplaced codes are fine', () => {
    expect(
      edited((a) => (at(a, ['result']).unplaced = Array(20).fill('ZZ 0000'))),
    ).toBe('ok');
  });
});

describe('rule nodes', () => {
  const nodeEdit = (change: (n: Json) => void) =>
    edited((a) => change(root(a)), 'draft-standard-mixed');
  const childEdit = (change: (n: Json) => void) =>
    edited((a) => change(at(root(a), ['children', 3])), 'draft-standard-mixed');
  it.each([
    ['kind', '', 'invalid'],
    ['kind', 'k'.repeat(32), 'ok'],
    ['kind', 'k'.repeat(33), 'invalid'],
    ['kind', astral(32), 'ok'],
    ['label', '', 'invalid'],
    ['label', 'l'.repeat(1000), 'ok'],
    ['label', 'l'.repeat(1001), 'invalid'],
    ['label', astral(1000), 'ok'],
    ['label', astral(1001), 'invalid'],
    ['status', 'done', 'invalid'],
    ['status', null, 'ok'],
    ['status', 'not_evaluated', 'ok'],
    ['reasons', Array(10).fill('r'), 'ok'],
    ['reasons', Array(11).fill('r'), 'invalid'],
    ['reasons', [1], 'invalid'],
    ['reasons_omitted', -1, 'invalid'],
    ['reasons_omitted', 2, 'ok'],
    ['counted', Array(20).fill('CS 5010'), 'ok'],
    ['counted', Array(21).fill('CS 5010'), 'invalid'],
    ['counted', [5010], 'invalid'],
    ['possible', Array(21).fill('CS 5010'), 'invalid'],
    ['possible', [null], 'invalid'],
    ['missing', Array(10).fill('CS 5010'), 'ok'],
    ['missing', Array(11).fill('CS 5010'), 'invalid'],
    ['missing', [{}], 'invalid'],
    ['missing_omitted', 0.5, 'invalid'],
    ['shortfall', [], 'invalid'],
    ['shortfall', null, 'invalid'],
    ['shortfall', { credits: -1 }, 'invalid'],
    ['shortfall', { credits: '8' }, 'invalid'],
    ['shortfall', { credits: 8, courses: 0 }, 'ok'],
  ])('node %s of %j', (key, value, kind) => {
    expect(childEdit((n) => (n[key] = value))).toBe(kind);
  });
  it.each([
    'kind',
    'label',
    'status',
    'reasons',
    'reasons_omitted',
    'counted',
    'possible',
    'missing',
    'missing_omitted',
    'shortfall',
    'children',
  ])('a node without %s is not readable, the status key included', (key) => {
    expect(childEdit((n) => delete n[key])).toBe('invalid');
  });
  it('40 children are fine, 41 are not; a bad child spoils the tree', () => {
    const many = (n: number) => (node: Json) =>
      (node.children = Array.from({ length: n }, () => leaf()));
    expect(nodeEdit(many(40))).toBe('ok');
    expect(nodeEdit(many(41))).toBe('invalid');
    expect(nodeEdit((n) => ((n.children as unknown[])[0] = 'leaf'))).toBe(
      'invalid',
    );
    expect(
      nodeEdit(
        (n) => ((n.children as unknown[])[0] = { ...leaf(), label: '' }),
      ),
    ).toBe('invalid');
    expect(nodeEdit((n) => (n.children = {}))).toBe('invalid');
  });
  it('the root is depth 0 and depth 20 is the deepest', () => {
    const chain = (depth: number) => {
      let node: DraftNode = leaf();
      for (let i = 0; i < depth; i++)
        node = { ...leaf('unknown'), children: [node] };
      return node;
    };
    expect(nodeEdit((n) => (n.children = [chain(19)]))).toBe('ok');
    expect(nodeEdit((n) => (n.children = [chain(20)]))).toBe('invalid');
    expect(edited((a) => (at(a, ['result']).root = chain(20)))).toBe('ok');
    expect(edited((a) => (at(a, ['result']).root = chain(21)))).toBe('invalid');
  });
});

describe('the reference vectors', () => {
  it('has the 18 failure and 7 tree vectors', () => {
    expect(failureVectors).toHaveLength(18);
    expect(treeVectors).toHaveLength(7);
  });
  it.each(failureVectors)(
    'failure $failure.status $failure.reason $failure.errorType: $text',
    ({ failure, text, retry }) => {
      expect(draftFailureMessage(failure)).toBe(text);
      expect(canRetryDraft(failure)).toBe(retry);
    },
  );
  it.each(treeVectors.map((v, i) => [i, v] as const))(
    'tree vector %i',
    (_, { node, lines }) => {
      expect(draftTreeLines(node)).toEqual(lines);
    },
  );
});

describe('small functions', () => {
  it.each([
    [0, '0 学分'],
    [4, '4 学分'],
    [12, '12 学分'],
    [null, '学分未知'],
  ])('creditsText(%j) is %s', (credits, text) => {
    expect(creditsText(credits)).toBe(text);
  });
  it.each([
    'constructor',
    'toString',
    '__proto__',
    'hasOwnProperty',
    'valueOf',
  ])('a node kind %s from Object.prototype has no operator word', (kind) => {
    expect(draftTreeLines({ ...leaf(), kind })[0]).toBe(
      '按你填的满足 — Synthetic leaf',
    );
  });
  it('the depth argument indents every line of the node and its children', () => {
    const node: DraftNode = {
      ...leaf('missing'),
      kind: 'any_of',
      missing: ['CS 5800'],
      children: [leaf(null)],
    };
    expect(draftTreeLines(node, 2)).toEqual([
      '    还缺 — 任选其一（OR） Synthetic leaf',
      '      缺项候选：CS 5800',
      '      仅列出，不自动判断 — Synthetic leaf',
    ]);
  });
  it('a code both counted and possible shows once, as possible', () => {
    expect(
      draftTreeLines({
        ...leaf('unknown'),
        counted: ['CS 5200', 'CS 5010', 'CS 5100'],
        possible: ['CS 5100', 'CS 5200'],
      }),
    ).toEqual([
      '不确定 — Synthetic leaf',
      '  按填写计入：CS 5010',
      '  可能计入／学分未知：CS 5100、CS 5200',
    ]);
  });
  it('a failure never shows the API detail and an unknown 409 reason may be retried', () => {
    const failure = {
      status: 409,
      errorType: 'conflict',
      retryAfter: null,
      invalidFields: [],
      reason: 'plan_stale',
    };
    expect(draftFailureMessage(failure)).toBe(
      '无法核对草案。请求未完成，请稍后手动重试。',
    );
    expect(canRetryDraft(failure)).toBe(true);
    expect(
      draftFailureMessage({ ...failure, status: 404, reason: 'stale' }),
    ).toBe('找不到这个培养方案或方案，草案没有计算。');
    expect(canRetryDraft({ ...failure, status: 503, reason: 'stale' })).toBe(
      true,
    );
  });
  it('the unavailable sentence is for a 409 only: a 503 with that reason is a plain failure', () => {
    const failure = {
      status: 503,
      errorType: 'server',
      retryAfter: null,
      invalidFields: [],
      reason: 'unavailable',
    };
    expect(draftFailureMessage(failure)).toBe(
      draftFailureMessage({ ...failure, reason: null }),
    );
    expect(draftFailureMessage(failure)).not.toContain('暂时无法核对所选方案');
  });
});
