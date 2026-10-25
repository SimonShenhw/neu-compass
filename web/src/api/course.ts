// R5b's view contract. The course detail is the API's own shape (generated, R2b); the rest is the page's.
import { queryOptions } from '@tanstack/react-query';
import { apiGet, apiPath } from './client';
import type { Schemas } from './types';

export type CourseDetail = Schemas['CourseDetailOut'];
export type CompareColumn =
  | { status: 'loading' }
  | { status: 'error'; httpStatus: number | null }
  | { status: 'ready'; body: unknown };
export interface ComparePageProps {
  ids: readonly string[];
  columns: Readonly<Record<string, CompareColumn>>;
  onRemove: (id: string) => void;
  onClear: () => void;
  onReload: () => void;
}

// GET /course/{course_id}, the body as it came: each page checks the fields it reads (R5b, R3b). A course reads the
// same for everyone, so the key names no viewer; nothing here logs the path, which carries the course (R0 14.1).
export function courseQuery(courseId: string) {
  return queryOptions({
    queryKey: ['course', courseId],
    queryFn: ({ signal }) =>
      apiGet(apiPath('/course/{course_id}', { course_id: courseId }), {
        timeout: 'slow',
        signal,
      }),
  });
}

// Handwritten R3b response contract; runtime parsing is deliberately separate. It stays hand-written beside the
// generated CourseDetail, as R3a's requisites types do: the generated type marks every field with a default optional
// (the API always sends them), and the page wants them all present. course.types.test.ts ties it to the API (R2b).
export interface CatalogSnapshot {
  course_code: string;
  course_name: string;
  description: string | null;
  credits: number | null;
  prereq_codes: string[];
  catalog_url: string;
  snapshot_id: string;
  imported_at: string;
  retrieved_at: string | null;
}
export interface AnswerEvidence {
  catalog: CatalogSnapshot | null;
  source_review_ids: string[];
  missing_fields: string[];
  warnings: string[];
}
export interface EvidenceSnippet {
  field: string;
  value: unknown;
  source_id: string;
  quote: string;
  confidence: number;
}
export interface CourseDetailBody {
  course_id: string;
  primary_code: string;
  primary_name: string;
  term: string | null;
  credits: number | null;
  delivery_mode: 'in_person' | 'online' | 'hybrid' | 'async' | null;
  workload_hours_per_week: number | null;
  difficulty_score: number | null;
  grading_components: { name: string; weight: number | null }[];
  topics_covered: string[];
  program_context: {
    program_id: string;
    program_name: string;
    requirement_type: string;
    semester_recommended: number | null;
  }[];
  professor: string[];
  skill_tags: string[];
  career_relevance: string[];
  ai_policy: null | {
    permitted_tools: string[];
    banned_tools: string[];
    disclosure_required: boolean;
    notes: string | null;
  };
  evidence_snippets: EvidenceSnippet[];
  answer_evidence?: AnswerEvidence | null;
  course_requisites?: unknown;
  prerequisites: unknown;
}
