export interface RequisitesFixture {
  case: string;
  notes: string;
  body: {
    course_id: string;
    primary_code: string;
    primary_name: string;
    course_requisites?: unknown;
    prerequisites: unknown;
  };
}
const exports = import.meta.glob<RequisitesFixture>('./requisites/*.json', {
  eager: true,
  import: 'default',
});
export const requisitesFixtures = Object.values(exports);
export const DEFAULT_REQUISITES_CASE = 'cs-6140-two-years';
export function requisitesFixture(value: string | null) {
  return (
    requisitesFixtures.find((fixture) => fixture.case === value) ??
    requisitesFixtures.find(
      (fixture) => fixture.case === DEFAULT_REQUISITES_CASE,
    )!
  );
}
