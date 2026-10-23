export type Grade =
  | 'A+'
  | 'A'
  | 'A-'
  | 'B+'
  | 'B'
  | 'B-'
  | 'C+'
  | 'C'
  | 'C-'
  | 'D+'
  | 'D'
  | 'D-'
  | 'F'
  | 'P'
  | 'S';
export type RequisiteNode =
  | {
      kind: 'course';
      course_code: string;
      minimum_grade: Grade | null;
      academic_level: 'Graduate' | 'Undergraduate' | null;
      concurrent_allowed: boolean;
      children: [];
    }
  | { kind: 'all_of' | 'any_of'; children: RequisiteNode[] };
export type RequisiteSection =
  | { status: 'not_listed' }
  | { status: 'unparsed'; raw_text: string; reason: string }
  | { status: 'parsed'; raw_text: string; rule: RequisiteNode };
export interface RequisiteDocument {
  course_id: string;
  course_code: string;
  course_name: string;
  catalog_year: string;
  source: {
    url: string;
    catalog_year: string;
    captured_at: string;
    sha256: string;
  };
  requisites: { prerequisite: RequisiteSection; corequisite: RequisiteSection };
  description_evidence: null | {
    status: 'not_listed' | 'no_keyword_match' | 'review_needed';
    paragraphs: string[];
    candidates: { paragraph_index: number; markers: string[] }[];
  };
  credit_hours: null | {
    raw_text: string;
    kind: 'fixed' | 'range';
    minimum: string;
    maximum: string;
  };
  imported_at: string;
}
export interface ProgramNode {
  kind:
    | 'course'
    | 'all_of'
    | 'any_of'
    | 'select'
    | 'optional'
    | 'condition'
    | 'unmodeled';
  label: string;
  course_code: string | null;
  children: ProgramNode[];
  course_codes: string[];
  subject_codes: string[];
  course_ranges: { start: string; end: string }[];
  excluded_course_codes: string[];
  activate_when: string | null;
  min_courses: number | null;
  min_credits: number | null;
  min_areas: number | null;
  areas: Record<string, string[]>;
}
export interface ProgramPlan {
  plan_id: string;
  program_id: string;
  campus: string;
  catalog_year: string;
  pathway: 'standard' | 'align' | 'bridge';
  concentration: string | null;
  coverage: 'partial' | 'complete';
  checked_on: string;
  source_url: string;
  source_catalog_year: string;
  source_excerpt: string;
  source_html_sha256: string | null;
  captured_on: string;
  notes: string;
  requirements: ProgramNode;
}
export interface ProgramContext {
  course_code: string;
  catalog_year: string;
  schema_available: boolean;
  plans: ProgramPlan[];
  unusable_records: number;
  unreviewed_records: number;
  warnings: string[];
}
export interface RequisiteListing {
  schema_available: boolean;
  has_any_stored_records: boolean;
  documents: RequisiteDocument[];
  unusable_records: number;
  warnings: string[];
  program_contexts: ProgramContext[];
}
export interface LegacyPrerequisite {
  course_id: string;
  primary_code: string | null;
  primary_name: string | null;
  requirement: string;
}
