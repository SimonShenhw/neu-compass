import type {
  LegacyPrerequisite,
  ProgramContext,
  ProgramNode,
  ProgramPlan,
  RequisiteDocument,
  RequisiteListing,
  RequisiteNode,
  RequisiteSection,
} from '../api/requisites';

export type ParsedRequisites =
  | { kind: 'absent' }
  | { kind: 'invalid' }
  | { kind: 'ok'; listing: RequisiteListing };
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);
const string = (v: unknown): v is string => typeof v === 'string';
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every(string);
const integer = (v: unknown): v is number =>
  typeof v === 'number' && Number.isInteger(v);
const count = (v: unknown) => integer(v) && v >= 0;
const nullableString = (v: unknown) => v === null || string(v);
const oneOf = (v: unknown, values: string[]) => string(v) && values.includes(v);
// Require a full-string match without URL normalization or canonicalization.
const matches = (pattern: RegExp, v: unknown): v is string =>
  string(v) && v.match(pattern)?.[0] === v;
const hash = (v: unknown) => matches(/^[a-f0-9]{64}$/, v);
function year(v: unknown) {
  return (
    matches(/^\d{4}-\d{4}$/, v) &&
    Number(v.slice(5)) === Number(v.slice(0, 4)) + 1
  );
}
const fields = (v: Record<string, unknown>, names: string[]) =>
  names.every((name) => string(v[name]));

function requisiteTree(value: unknown): value is RequisiteNode {
  let nodes = 0;
  function visit(v: unknown, depth: number): boolean {
    if (++nodes > 120 || depth > 10 || !object(v) || !Array.isArray(v.children))
      return false;
    if (v.kind === 'course')
      return (
        string(v.course_code) &&
        v.children.length === 0 &&
        (v.minimum_grade === null ||
          oneOf(v.minimum_grade, [
            'A+',
            'A',
            'A-',
            'B+',
            'B',
            'B-',
            'C+',
            'C',
            'C-',
            'D+',
            'D',
            'D-',
            'F',
            'P',
            'S',
          ])) &&
        (v.academic_level === null ||
          v.academic_level === 'Graduate' ||
          v.academic_level === 'Undergraduate') &&
        typeof v.concurrent_allowed === 'boolean'
      );
    return (
      (v.kind === 'all_of' || v.kind === 'any_of') &&
      v.course_code === null &&
      v.minimum_grade === null &&
      v.academic_level === null &&
      v.concurrent_allowed === false &&
      v.children.length >= 2 &&
      v.children.every((child) => visit(child, depth + 1))
    );
  }
  return visit(value, 1);
}
function section(v: unknown): v is RequisiteSection {
  if (!object(v)) return false;
  if (v.status === 'not_listed')
    return v.raw_text === null && v.rule === null && v.reason === null;
  if (v.status === 'unparsed')
    return (
      string(v.raw_text) &&
      string(v.reason) &&
      v.reason.length > 0 &&
      v.rule === null
    );
  return (
    v.status === 'parsed' &&
    string(v.raw_text) &&
    v.raw_text.trim().length > 0 &&
    v.reason === null &&
    requisiteTree(v.rule)
  );
}
function description(v: unknown): boolean {
  if (v === null) return true;
  if (
    !object(v) ||
    !oneOf(v.status, ['not_listed', 'no_keyword_match', 'review_needed']) ||
    !strings(v.paragraphs) ||
    !Array.isArray(v.candidates)
  )
    return false;
  const length = v.paragraphs.length;
  return v.candidates.every(
    (c: unknown) =>
      object(c) &&
      integer(c.paragraph_index) &&
      c.paragraph_index >= 0 &&
      c.paragraph_index < length &&
      strings(c.markers) &&
      c.markers.length > 0,
  );
}
function document(v: unknown): v is RequisiteDocument {
  if (
    !object(v) ||
    !fields(v, ['course_id', 'course_code', 'course_name', 'imported_at']) ||
    !year(v.catalog_year) ||
    !object(v.source) ||
    !string(v.course_code)
  )
    return false;
  const subject = v.course_code.trim().split(/\s+/)[0]!.toLowerCase();
  return (
    v.source.catalog_year === v.catalog_year &&
    string(v.source.captured_at) &&
    hash(v.source.sha256) &&
    v.source.url ===
      `https://catalog.northeastern.edu/course-descriptions/${subject}/` &&
    object(v.requisites) &&
    section(v.requisites.prerequisite) &&
    section(v.requisites.corequisite) &&
    description(v.description_evidence) &&
    (v.credit_hours === null ||
      (object(v.credit_hours) &&
        fields(v.credit_hours, ['raw_text', 'minimum', 'maximum']) &&
        (v.credit_hours.kind === 'fixed' || v.credit_hours.kind === 'range')))
  );
}
export function programTree(value: unknown): value is ProgramNode {
  let nodes = 0;
  function visit(v: unknown, depth: number): boolean {
    if (
      ++nodes > 120 ||
      depth > 8 ||
      !object(v) ||
      !string(v.label) ||
      !Array.isArray(v.children)
    )
      return false;
    if (
      !oneOf(v.kind, [
        'course',
        'all_of',
        'any_of',
        'select',
        'optional',
        'condition',
        'unmodeled',
      ])
    )
      return false;
    if (v.kind === 'course' && !string(v.course_code)) return false;
    if ((v.kind === 'all_of' || v.kind === 'any_of') && v.children.length < 2)
      return false;
    if (
      v.kind === 'optional' &&
      (!string(v.activate_when) || v.children.length !== 1)
    )
      return false;
    if (
      v.kind === 'select' &&
      (!strings(v.course_codes) ||
        !strings(v.subject_codes) ||
        !strings(v.excluded_course_codes) ||
        !Array.isArray(v.course_ranges) ||
        !v.course_ranges.every(
          (r: unknown) => object(r) && string(r.start) && string(r.end),
        ) ||
        ![v.min_courses, v.min_credits, v.min_areas].every(
          (n) => n === null || integer(n),
        ) ||
        !object(v.areas) ||
        !Object.values(v.areas).every(strings))
    )
      return false;
    return v.children.every((child) => visit(child, depth + 1));
  }
  return visit(value, 1);
}
function plan(v: unknown, catalogYear: string): v is ProgramPlan {
  return (
    object(v) &&
    fields(v, [
      'plan_id',
      'program_id',
      'campus',
      'source_excerpt',
      'notes',
      'captured_on',
      'checked_on',
      'source_catalog_year',
    ]) &&
    v.catalog_year === catalogYear &&
    oneOf(v.pathway, ['standard', 'align', 'bridge']) &&
    nullableString(v.concentration) &&
    (v.coverage === 'partial' || v.coverage === 'complete') &&
    (v.source_html_sha256 === null || hash(v.source_html_sha256)) &&
    matches(
      /^https:\/\/catalog\.northeastern\.edu\/(archive\/\d{4}-\d{4}\/)?graduate\/[a-z0-9/-]+\/$/,
      v.source_url,
    ) &&
    programTree(v.requirements)
  );
}
function context(v: unknown): v is ProgramContext {
  if (
    !object(v) ||
    !string(v.course_code) ||
    !string(v.catalog_year) ||
    typeof v.schema_available !== 'boolean' ||
    !Array.isArray(v.plans) ||
    !count(v.unusable_records) ||
    !count(v.unreviewed_records) ||
    !strings(v.warnings)
  )
    return false;
  if (!v.schema_available && v.plans.length > 0) return false;
  const catalogYear = v.catalog_year;
  const ids = new Set<string>();
  return v.plans.every((p: unknown) => {
    if (!plan(p, catalogYear) || ids.has(p.plan_id)) return false;
    ids.add(p.plan_id);
    return true;
  });
}
export function parseRequisites(value: unknown): ParsedRequisites {
  if (value === undefined || value === null) return { kind: 'absent' };
  if (
    !object(value) ||
    typeof value.schema_available !== 'boolean' ||
    typeof value.has_any_stored_records !== 'boolean' ||
    !Array.isArray(value.documents) ||
    !Array.isArray(value.program_contexts) ||
    !strings(value.warnings) ||
    !count(value.unusable_records) ||
    !value.documents.every(document) ||
    !value.program_contexts.every(context)
  )
    return { kind: 'invalid' };
  const documents = value.documents;
  const pairs = new Set<string>();
  for (const c of value.program_contexts) {
    const pair = JSON.stringify([c.course_code, c.catalog_year]);
    if (
      pairs.has(pair) ||
      !documents.some(
        (d) =>
          d.course_code === c.course_code && d.catalog_year === c.catalog_year,
      )
    )
      return { kind: 'invalid' };
    pairs.add(pair);
  }
  return { kind: 'ok', listing: value as unknown as RequisiteListing };
}
export function legacyPrerequisites(value: unknown): LegacyPrerequisite[] {
  if (
    !Array.isArray(value) ||
    !value.every(
      (v: unknown) =>
        object(v) &&
        string(v.course_id) &&
        nullableString(v.primary_code) &&
        nullableString(v.primary_name) &&
        string(v.requirement),
    )
  )
    return [];
  return value as LegacyPrerequisite[];
}
export function legacyLabelsAllowed(parsed: ParsedRequisites) {
  return (
    parsed.kind === 'absent' ||
    (parsed.kind === 'ok' &&
      !parsed.listing.has_any_stored_records &&
      parsed.listing.documents.length === 0 &&
      parsed.listing.unusable_records === 0 &&
      !parsed.listing.warnings.includes('structured_requisite_schema_unusable'))
  );
}
