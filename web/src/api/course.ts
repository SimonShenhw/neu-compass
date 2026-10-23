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
