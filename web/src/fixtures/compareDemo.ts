import type { CompareColumn } from '../api/course';
import { createCompareList } from '../models/compareList';
import cs5800 from './compare/course-cs-5800.json';
import cs6140 from './compare/course-cs-6140.json';
import ds5220 from './compare/course-ds-5220.json';
import cs5100 from './compare/course-cs-5100.json';
import cs7800 from './compare/course-cs-7800.json';
import unavailable from './compare/course-cs-5800-requisites-unavailable.json';
import notFound from './compare/course-404.json';

const four = [
  cs5800.body.course_id,
  cs6140.body.course_id,
  ds5220.body.course_id,
  cs5100.body.course_id,
];
const cases = {
  four,
  one: [cs7800.body.course_id],
  empty: [],
  failed: [
    cs5800.body.course_id,
    'c-not-in-the-catalog',
    cs6140.body.course_id,
    'demo-network',
  ],
  unrecognised: ['demo-null', 'demo-array', 'c2'],
  'bad-cell': [cs5800.body.course_id, cs6140.body.course_id],
  loading: [cs5800.body.course_id, cs6140.body.course_id],
  'requisites-unavailable': [cs5800.body.course_id],
};
export type CompareDemoCase = keyof typeof cases;
export const compareCaseOptions = Object.keys(cases) as CompareDemoCase[];
export function readCompareCase(value: string | null): CompareDemoCase {
  return value && Object.hasOwn(cases, value)
    ? (value as CompareDemoCase)
    : 'four';
}
// The demo's own list (R5d): a case fills it, and the student's comparison list on /compare stays as it was.
export const demoList = createCompareList();
// The demo seeds once per selected case, not on every route remount. It must not
// resurrect courses the user removed or a list cleared by a future auth adapter.
let activeCase: CompareDemoCase | null = null;
export function activateCompareCase(value: CompareDemoCase) {
  if (activeCase === value) return;
  activeCase = value;
  demoList.clear();
  for (const id of cases[value]) demoList.add(id);
}
export function resetCompareDemoForTests() {
  activeCase = null;
  demoList.clear();
}
export function demoColumns(
  value: CompareDemoCase,
): Readonly<Record<string, CompareColumn>> {
  const result: Record<string, CompareColumn> = Object.fromEntries(
    [cs5800, cs6140, ds5220, cs5100, cs7800].map((f) => [
      f.body.course_id,
      { status: 'ready', body: f.body },
    ]),
  );
  if (value === 'failed') {
    result['c-not-in-the-catalog'] = {
      status: 'error',
      httpStatus: notFound.status,
    };
    result['demo-network'] = { status: 'error', httpStatus: null };
  }
  if (value === 'unrecognised') {
    result['demo-null'] = { status: 'ready', body: null };
    result['demo-array'] = { status: 'ready', body: [] };
    result.c2 = { status: 'ready', body: { course_id: 'c2' } };
  }
  if (value === 'bad-cell')
    result[cs5800.body.course_id] = {
      status: 'ready',
      body: { ...cs5800.body, grading_components: 'not a list' },
    };
  if (value === 'loading')
    for (const id of cases.loading) result[id] = { status: 'loading' };
  if (value === 'requisites-unavailable')
    result[cs5800.body.course_id] = { status: 'ready', body: unavailable.body };
  return result;
}
