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
