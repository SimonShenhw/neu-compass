import { expectTypeOf, it } from 'vitest';
import type {
  LegacyPrerequisite,
  ProgramContext,
  ProgramNode,
  ProgramPlan,
  RequisiteDocument,
  RequisiteListing,
  RequisiteNode,
  RequisiteSection,
} from './requisites';
import type { Schemas } from './types';
import type { Misfits } from '../test/misfits';

// R3a's types are the panel's view of GET /course/{id}: one shape per kind or status, without the fields the panel
// never reads, so they stay hand-written and narrower than the generated ones. These checks are for the compiler
// (npm run typecheck): they fail when the API drops or renames a field the panel reads, or may send a value the
// panel's checks refuse (R2b). models/requisites.ts checks the rest at run time.

type Evidence = NonNullable<RequisiteDocument['description_evidence']>;

it('the requisites panel reads only fields the API has, with values the API may send', () => {
  expectTypeOf<
    Misfits<RequisiteListing, Schemas['CourseRequisiteListing']>
  >().toBeNever();
  expectTypeOf<
    Misfits<RequisiteDocument, Schemas['CourseRequisiteDocument']>
  >().toBeNever();
  expectTypeOf<
    Misfits<RequisiteDocument['source'], Schemas['CourseRequisiteSource']>
  >().toBeNever();
  expectTypeOf<
    Misfits<RequisiteDocument['requisites'], Schemas['CatalogRequisites']>
  >().toBeNever();
  expectTypeOf<
    Misfits<RequisiteSection, Schemas['RequisiteSection']>
  >().toBeNever();
  expectTypeOf<Misfits<RequisiteNode, Schemas['RequisiteNode']>>().toBeNever();
  expectTypeOf<
    Misfits<Evidence, Schemas['CourseDescriptionEvidence']>
  >().toBeNever();
  expectTypeOf<
    Misfits<Evidence['candidates'][number], Schemas['DescriptionCandidate']>
  >().toBeNever();
  expectTypeOf<
    Misfits<
      NonNullable<RequisiteDocument['credit_hours']>,
      Schemas['CatalogCreditHours']
    >
  >().toBeNever();
  expectTypeOf<
    Misfits<ProgramContext, Schemas['CourseProgramContext']>
  >().toBeNever();
  expectTypeOf<Misfits<ProgramPlan, Schemas['ProgramPlan']>>().toBeNever();
  expectTypeOf<Misfits<ProgramNode, Schemas['RequirementNode']>>().toBeNever();
  // Misfits passes over fields whose values are objects; areas is the one the panel reads with no check of its own.
  expectTypeOf<NonNullable<Schemas['RequirementNode']['areas']>>().toExtend<
    ProgramNode['areas']
  >();
  expectTypeOf<
    Misfits<ProgramNode['course_ranges'][number], Schemas['CourseRange']>
  >().toBeNever();
  expectTypeOf<
    Misfits<LegacyPrerequisite, Schemas['CoursePrereqOut']>
  >().toBeNever();
});

it('the panel takes its listing and legacy rows from the course detail fields that carry them', () => {
  expectTypeOf<
    NonNullable<Schemas['CourseDetailOut']['course_requisites']>
  >().toEqualTypeOf<Schemas['CourseRequisiteListing']>();
  expectTypeOf<
    NonNullable<Schemas['CourseDetailOut']['prerequisites']>
  >().toEqualTypeOf<Schemas['CoursePrereqOut'][]>();
});
