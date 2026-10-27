import { queryOptions } from '@tanstack/react-query';
import { apiGet, apiPath } from './client';
import { PUBLIC_FRESH_MS } from './queries';
import type { ProgramNode } from './requisites';

// GET /programs and GET /programs/{id} (R3e): public lists, fresh for five minutes as in Streamlit (R0 0.5), one cache
// for the search page's selectors and landing and, from R4, the program pages (R3d spec 2). The bodies come as they
// are: each page checks what it reads (models/programs.ts, programPlans.ts, chatPlans.ts).
export const programListQuery = queryOptions({
  queryKey: ['programs'],
  queryFn: ({ signal }) =>
    apiGet(apiPath('/programs'), { timeout: 'read', signal }),
  staleTime: PUBLIC_FRESH_MS,
});

export function curriculumQuery(programId: string) {
  return queryOptions({
    queryKey: ['programs', programId],
    queryFn: ({ signal }) =>
      apiGet(apiPath('/programs/{program_id}', { program_id: programId }), {
        timeout: 'read',
        signal,
      }),
    staleTime: PUBLIC_FRESH_MS,
  });
}

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
