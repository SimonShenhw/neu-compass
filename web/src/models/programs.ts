import type {
  ProgramSummary,
  ProgramCurriculum,
  CurriculumSemester,
  CurriculumCourse,
} from '../api/programs';
import { boundedText, integer, list, object, string } from './searchGuard';

type Parsed<T> = { kind: 'ok'; data: T } | { kind: 'invalid' };
const invalid = { kind: 'invalid' } as const;
const nullableText = (v: unknown): v is string | null | undefined =>
  v == null || string(v);

export function parseProgramList(value: unknown): Parsed<ProgramSummary[]> {
  const rows = list(
    value,
    (v): v is ProgramSummary =>
      object(v) &&
      boundedText(v.program_id, 1, 64) &&
      string(v.prefix) &&
      string(v.full_name) &&
      integer(v.course_count) &&
      integer(v.plan_count),
  );
  return rows && new Set(rows.map((r) => r.program_id)).size === rows.length
    ? { kind: 'ok', data: rows }
    : invalid;
}
function course(v: unknown): CurriculumCourse | null {
  if (
    !object(v) ||
    !string(v.course_id) ||
    v.course_id === '' ||
    !string(v.primary_code) ||
    !string(v.primary_name) ||
    !string(v.requirement_type) ||
    !nullableText(v.notes)
  )
    return null;
  return {
    course_id: v.course_id,
    primary_code: v.primary_code,
    primary_name: v.primary_name,
    requirement_type: v.requirement_type,
    notes: v.notes ?? null,
  };
}
function semester(v: unknown): CurriculumSemester | null {
  if (
    !object(v) ||
    !(v.semester == null || integer(v.semester, 1, 8)) ||
    !Array.isArray(v.courses)
  )
    return null;
  const courses = Array.from(v.courses).map(course);
  if (courses.some((c) => c === null)) return null;
  return {
    semester: v.semester ?? null,
    courses: courses as CurriculumCourse[],
  };
}
export function parseCurriculum(
  value: unknown,
  programId: string,
): Parsed<ProgramCurriculum> {
  if (
    !object(value) ||
    value.program_id !== programId ||
    !string(value.prefix) ||
    !string(value.full_name) ||
    !nullableText(value.notes) ||
    !Array.isArray(value.semesters) ||
    !Array.isArray(value.plans) ||
    typeof value.plan_schema_available !== 'boolean'
  )
    return invalid;
  const semesters = Array.from(value.semesters).map(semester);
  if (semesters.some((s) => s === null)) return invalid;
  return {
    kind: 'ok',
    data: {
      program_id: programId,
      prefix: value.prefix,
      full_name: value.full_name,
      notes: value.notes ?? null,
      semesters: semesters as CurriculumSemester[],
      plans: value.plans,
      plan_schema_available: value.plan_schema_available,
    },
  };
}
