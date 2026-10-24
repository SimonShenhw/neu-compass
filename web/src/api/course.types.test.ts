import { expectTypeOf, it } from 'vitest';
import type {
  AnswerEvidence,
  CatalogSnapshot,
  CourseDetailBody,
  EvidenceSnippet,
} from './course';
import type { Schemas } from './types';
import type { Misfits } from '../test/misfits';

// R3b's types are the course detail page's view of GET /course/{id}, hand-written with every field present, so they
// are narrower than the generated ones. These checks are for the compiler (npm run typecheck): they fail when the API
// drops or renames a field the page reads, or may send a value the page's types refuse (R2b). models/courseDetail.ts
// checks the rest at run time; the requisites and legacy rows are R3a's, checked in requisites.types.test.ts.

it('the course detail page reads only fields the API has, with values the API may send', () => {
  expectTypeOf<
    Misfits<CourseDetailBody, Schemas['CourseDetailOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<
      CourseDetailBody['grading_components'][number],
      Schemas['GradingComponent']
    >
  >().toBeNever();
  expectTypeOf<
    Misfits<
      CourseDetailBody['program_context'][number],
      Schemas['CourseProgramEdgeOut']
    >
  >().toBeNever();
  expectTypeOf<
    Misfits<NonNullable<CourseDetailBody['ai_policy']>, Schemas['AIPolicy']>
  >().toBeNever();
  expectTypeOf<
    Misfits<EvidenceSnippet, Schemas['EvidenceSnippet']>
  >().toBeNever();
  expectTypeOf<
    Misfits<AnswerEvidence, Schemas['CourseAnswerEvidence']>
  >().toBeNever();
  expectTypeOf<
    Misfits<CatalogSnapshot, Schemas['CatalogSnapshot']>
  >().toBeNever();
});
