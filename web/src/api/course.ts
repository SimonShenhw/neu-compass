// Handwritten R5b view contract; R2 will replace this with generated API types.
export interface CourseDetail {
  course_id: string;
  primary_code: string;
  primary_name: string;
  term: string | null;
  credits: number | null;
  delivery_mode: string | null;
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
  answer_evidence: unknown;
  course_requisites: unknown;
}
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

// Handwritten R3b response contract; runtime parsing is deliberately separate.
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
export interface CourseDetailBody extends Omit<
  CourseDetail,
  'delivery_mode' | 'answer_evidence' | 'course_requisites'
> {
  delivery_mode: 'in_person' | 'online' | 'hybrid' | 'async' | null;
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
