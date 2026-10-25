import { expectTypeOf, it } from 'vitest';
import type {
  ProgramSummary,
  ProgramCurriculum,
  CurriculumSemester,
  CurriculumCourse,
  ProgramPlanDoc,
  PolicyScope,
  PolicyLink,
  PolicyFragment,
  PolicyEvidence,
  ProgramPolicyView,
} from './programs';
import type { Schemas } from './types';
import type { Misfits } from '../test/misfits';

it('program view types stay compatible with generated API fields including nested rows', () => {
  expectTypeOf<
    Misfits<ProgramSummary, Schemas['ProgramSummaryOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<ProgramCurriculum, Schemas['ProgramCurriculumOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<CurriculumSemester, Schemas['CurriculumSemesterOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<CurriculumCourse, Schemas['CurriculumCourseOut']>
  >().toBeNever();
  // Reached through the fields too, so a field pointed at another shape fails here (as course.types.test.ts does).
  expectTypeOf<
    Misfits<
      ProgramCurriculum['semesters'][number],
      Schemas['CurriculumSemesterOut']
    >
  >().toBeNever();
  expectTypeOf<
    Misfits<
      ProgramCurriculum['semesters'][number]['courses'][number],
      Schemas['CurriculumCourseOut']
    >
  >().toBeNever();
});

it('plan and policy consumption types match every generated nested contract', () => {
  expectTypeOf<Misfits<ProgramPlanDoc, Schemas['ProgramPlan']>>().toBeNever();
  expectTypeOf<Misfits<PolicyScope, Schemas['PolicyScope']>>().toBeNever();
  expectTypeOf<Misfits<PolicyLink, Schemas['PlanPolicyLink']>>().toBeNever();
  expectTypeOf<
    Misfits<PolicyFragment, Schemas['PolicyFragmentOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<PolicyEvidence, Schemas['PolicyEvidenceOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<PolicyEvidence['source'], Schemas['SourceCapture']>
  >().toBeNever();
  expectTypeOf<
    Misfits<ProgramPolicyView, Schemas['ProgramPolicyView']>
  >().toBeNever();
});
