import { expectTypeOf, it } from 'vitest';
import type {
  ProgramSummary,
  ProgramCurriculum,
  CurriculumSemester,
  CurriculumCourse,
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
});
