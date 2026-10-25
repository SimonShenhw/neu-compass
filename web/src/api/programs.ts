import type { ProgramNode } from './requisites';

export interface ProgramSummary {
  program_id: string;
  full_name: string;
  prefix: string;
  course_count: number;
  plan_count: number;
}
export interface CurriculumCourse {
  course_id: string;
  primary_code: string;
  primary_name: string;
  requirement_type: string;
  notes: string | null;
}
export interface CurriculumSemester {
  semester: number | null;
  courses: CurriculumCourse[];
}
export interface ProgramCurriculum {
  program_id: string;
  full_name: string;
  prefix: string;
  notes: string | null;
  semesters: CurriculumSemester[];
  plans: unknown[];
  plan_schema_available: boolean;
}

export interface ProgramPlanDoc {
  plan_id: string;
  program_id: string;
  campus: string;
  catalog_year: string;
  pathway: 'standard' | 'align' | 'bridge';
  concentration: string | null;
  coverage: 'partial' | 'complete';
  review_status: 'draft' | 'source_checked';
  checked_by: string | null;
  checked_on: string | null;
  source_url: string;
  source_title: string;
  source_catalog_year: string;
  source_excerpt: string;
  source_html_sha256: string | null;
  captured_on: string;
  notes: string;
  requirements: ProgramNode;
}
export interface PolicyScope {
  program_id: string;
  campus: string;
  catalog_year: string;
  pathway: string;
  concentration: string | null;
}
export interface PolicyLink extends PolicyScope {
  plan_id: string;
  plan_content_sha256: string;
  home_college: 'khoury' | 'camd' | 'engineering';
  policy_ids: string[];
}
export interface PolicyFragment {
  fragment_id: string;
  source_kind: 'paragraph' | 'list';
  paragraph_index: number;
  heading: string | null;
  paragraph_sha256: string;
  summary: string;
  limitation: string;
  source_paragraph: string;
}
export interface PolicyEvidence {
  policy_id: string;
  authority: 'university' | 'khoury' | 'camd' | 'engineering';
  source: {
    url: string;
    catalog_year: string;
    captured_at: string;
    sha256: string;
    page_title: string;
  };
  fragments: PolicyFragment[];
}
export interface ProgramPolicyView {
  plan_id: string;
  scope: PolicyScope;
  plan_content_sha256: string;
  status:
    'ready' | 'not_linked' | 'draft' | 'stale' | 'unavailable' | 'unusable';
  link: PolicyLink | null;
  checked_by: string | null;
  checked_on: string | null;
  policies: PolicyEvidence[];
}
