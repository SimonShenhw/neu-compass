import { MAX_COMPARE_COURSES } from '../models/compareList';

export interface CourseDetailFixture {
  case: string;
  notes: string;
  body: {
    course_id: string;
    primary_code: string;
    primary_name: string;
    [key: string]: unknown;
  };
}
const exports = import.meta.glob<CourseDetailFixture>(
  './course-detail/*.json',
  { eager: true, import: 'default' },
);
export const courseDetailFixtures = Object.values(exports);
export function courseDetailFixture(value: string | null) {
  return (
    courseDetailFixtures.find((fixture) => fixture.case === value) ??
    courseDetailFixtures.find(
      (fixture) => fixture.case === 'cs-6140-everything',
    )!
  );
}
export const detailCompareOptions = [
  { value: 'empty', label: '空' },
  { value: 'has', label: '有这门课' },
  { value: 'full', label: '满了' },
  { value: 'full-with', label: '满了而且有这门课' },
] as const;
export type DetailCompareChoice =
  (typeof detailCompareOptions)[number]['value'];
export function detailCompareChoice(value: string | null): DetailCompareChoice {
  return (
    detailCompareOptions.find((option) => option.value === value)?.value ??
    'empty'
  );
}
export function detailCompareIds(
  choice: DetailCompareChoice,
  courseId: string,
): string[] {
  const others = Array.from(
    { length: MAX_COMPARE_COURSES },
    (_, index) => `c-other-${index}`,
  );
  if (choice === 'has') return [others[0]!, courseId];
  if (choice === 'full') return others;
  if (choice === 'full-with')
    return [...others.slice(0, MAX_COMPARE_COURSES - 1), courseId];
  return [];
}
