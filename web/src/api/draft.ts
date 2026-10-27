// R4b: the answer of POST /programs/{program_id}/plans/{plan_id}/draft, as the draft component reads it. Hand-written
// like the other page types; draft.types.test.ts checks them against the generated ones. The request (sent by the R4
// wiring) is {plan_content_sha256, course_ids, input}: the version the page shows, the draft's course IDs (at most
// 20) and the newly typed text (at most 4000 characters). The draft lives in memory only.
export interface DraftCourse {
  course_id: string;
  code: string;
  name: string;
  credits: number | null;
}
export type DraftNoticeKind =
  | 'course_gone'
  | 'duplicate_code'
  | 'too_many_codes'
  | 'invalid_format'
  | 'invalid_format_more'
  | 'all_present'
  | 'over_limit'
  | 'not_found'
  | 'ambiguous'
  | 'cross_listed_twin'
  | 'also_matches'
  | 'primary_code'
  | 'invalid_record'
  | 'nothing_new';
export interface DraftCandidate {
  code: string;
  name: string;
}
export interface DraftNotice {
  kind: DraftNoticeKind;
  level: 'warning' | 'info';
  text: string;
  candidates: DraftCandidate[];
  candidates_omitted: number;
}
export interface DraftNode {
  kind: string;
  label: string;
  status: 'met' | 'missing' | 'unknown' | 'not_evaluated' | null;
  reasons: string[];
  reasons_omitted: number;
  counted: string[];
  possible: string[];
  missing: string[];
  missing_omitted: number;
  shortfall: Record<string, number>;
  children: DraftNode[];
}
export interface DraftResult {
  root: DraftNode;
  unplaced: string[];
  summary_counts: { met: number; missing: number; unknown: number };
}
export interface DraftAnswer {
  plan_content_sha256: string;
  courses: DraftCourse[];
  added: string[];
  notices: DraftNotice[];
  result: DraftResult;
}
