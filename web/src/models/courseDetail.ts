import type {
  AnswerEvidence,
  CatalogSnapshot,
  CourseDetailBody,
} from '../api/course';
import { utcMinute } from './courseDetailFormat';

type CatalogState =
  | { kind: 'absent' }
  | { kind: 'invalid' }
  | { kind: 'ok'; snapshot: CatalogSnapshot };
export type ParsedAnswerEvidence = Omit<AnswerEvidence, 'catalog'> & {
  catalog: CatalogState;
};
export type DetailView = Omit<CourseDetailBody, 'answer_evidence'> & {
  answer_evidence: ParsedAnswerEvidence | null;
};
export type ParsedCourseDetail =
  { kind: 'invalid' } | { kind: 'ok'; body: DetailView };
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === 'string';
const nonempty = (v: unknown): v is string => string(v) && v.length > 0;
const nullableString = (v: unknown): v is string | null =>
  v === null || string(v);
const number = (v: unknown, min: number, max = Infinity): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max;
const integer = (v: unknown, min: number, max: number): v is number =>
  number(v, min, max) && Number.isInteger(v);
function list<T>(v: unknown, check: (item: unknown) => item is T): T[] | null {
  return Array.isArray(v) && Array.from(v).every(check)
    ? ([...v] as T[])
    : null;
}
const strings = (v: unknown) => list(v, string);
function timestamp(v: unknown): v is string {
  if (!string(v)) return false;
  try {
    utcMinute(v);
    return true;
  } catch {
    return false;
  }
}
export function catalog(value: unknown): CatalogState {
  if (
    value == null ||
    value === '' ||
    value === 0 ||
    value === false ||
    (Array.isArray(value) && value.length === 0) ||
    (object(value) && Object.keys(value).length === 0)
  )
    return { kind: 'absent' };
  if (!object(value) || !string(value.course_code)) return { kind: 'invalid' };
  const code = value.course_code
    .trim()
    .toUpperCase()
    .match(/^([A-Z]{2,4})\s?(\d{4}[A-Z]?)$/);
  // Pydantic's optional snapshot fields have defaults; explicit null prereq_codes is still invalid.
  const description =
    value.description === undefined ? null : value.description;
  const credits = value.credits === undefined ? null : value.credits;
  const retrieved =
    value.retrieved_at === undefined ? null : value.retrieved_at;
  const prereqs = strings(
    value.prereq_codes === undefined ? [] : value.prereq_codes,
  );
  if (
    !code ||
    !nonempty(value.course_name) ||
    !nullableString(description) ||
    (description !== null && Array.from(description).length > 20000) ||
    (credits !== null && !integer(credits, 0, 12)) ||
    !prereqs ||
    !string(value.snapshot_id) ||
    !timestamp(value.imported_at) ||
    (retrieved !== null && !timestamp(retrieved)) ||
    value.catalog_url !==
      `https://catalog.northeastern.edu/course-descriptions/${code[1]!.toLowerCase()}/`
  )
    return { kind: 'invalid' };
  return {
    kind: 'ok',
    snapshot: {
      course_code: `${code[1]} ${code[2]}`,
      course_name: value.course_name,
      description,
      credits,
      prereq_codes: prereqs,
      catalog_url: value.catalog_url as string,
      snapshot_id: value.snapshot_id,
      imported_at: value.imported_at,
      retrieved_at: retrieved,
    },
  };
}
export function evidence(v: unknown): ParsedAnswerEvidence | null {
  if (!object(v)) return null;
  const missing = strings(v.missing_fields ?? []),
    warnings = strings(v.warnings ?? []),
    sources = strings(v.source_review_ids ?? []);
  if (!missing || !warnings || !sources) return null;
  return {
    catalog: catalog(v.catalog),
    missing_fields: missing,
    warnings,
    source_review_ids: sources,
  };
}
function grading(
  v: unknown,
): v is CourseDetailBody['grading_components'][number] {
  return (
    object(v) &&
    nonempty(v.name) &&
    (v.weight === null || number(v.weight, 0, 1))
  );
}
type Placement = Omit<
  CourseDetailBody['program_context'][number],
  'program_id'
> & {
  program_id?: unknown;
};
function placement(v: unknown): v is Placement {
  return (
    object(v) &&
    string(v.program_name) &&
    string(v.requirement_type) &&
    (v.semester_recommended === null || integer(v.semester_recommended, 1, 8))
  );
}
function policy(v: unknown): CourseDetailBody['ai_policy'] {
  if (!object(v)) return null;
  const permitted = strings(v.permitted_tools),
    banned = strings(v.banned_tools);
  if (
    !permitted ||
    !banned ||
    typeof v.disclosure_required !== 'boolean' ||
    !nullableString(v.notes)
  )
    return null;
  return {
    permitted_tools: permitted,
    banned_tools: banned,
    disclosure_required: v.disclosure_required,
    notes: v.notes,
  };
}
function snippet(
  v: unknown,
): v is CourseDetailBody['evidence_snippets'][number] {
  return (
    object(v) &&
    string(v.field) &&
    string(v.source_id) &&
    string(v.quote) &&
    number(v.confidence, 0, 1)
  );
}
export function parseCourseDetail(value: unknown): ParsedCourseDetail {
  if (
    !object(value) ||
    !nonempty(value.course_id) ||
    !nonempty(value.primary_code) ||
    !nonempty(value.primary_name)
  )
    return { kind: 'invalid' };
  return {
    kind: 'ok',
    body: {
      course_id: value.course_id,
      primary_code: value.primary_code,
      primary_name: value.primary_name,
      term: string(value.term) ? value.term : null,
      credits: integer(value.credits, 0, 12) ? value.credits : null,
      delivery_mode:
        value.delivery_mode === 'in_person' ||
        value.delivery_mode === 'online' ||
        value.delivery_mode === 'hybrid' ||
        value.delivery_mode === 'async'
          ? value.delivery_mode
          : null,
      professor: strings(value.professor) ?? [],
      topics_covered: strings(value.topics_covered) ?? [],
      skill_tags: strings(value.skill_tags) ?? [],
      career_relevance: strings(value.career_relevance) ?? [],
      workload_hours_per_week: number(value.workload_hours_per_week, 0)
        ? value.workload_hours_per_week
        : null,
      difficulty_score: number(value.difficulty_score, 1, 5)
        ? value.difficulty_score
        : null,
      grading_components: list(value.grading_components, grading) ?? [],
      program_context: (list(value.program_context, placement) ?? []).map(
        (p) => ({ ...p, program_id: string(p.program_id) ? p.program_id : '' }),
      ),
      ai_policy: policy(value.ai_policy),
      evidence_snippets: list(value.evidence_snippets, snippet) ?? [],
      answer_evidence: evidence(value.answer_evidence),
      course_requisites: value.course_requisites,
      prerequisites: value.prerequisites,
    },
  };
}
