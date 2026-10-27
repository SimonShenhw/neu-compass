import { expectTypeOf, it } from 'vitest';
import type {
  DraftAnswer,
  DraftCandidate,
  DraftCourse,
  DraftNode,
  DraftNotice,
  DraftResult,
} from './draft';
import type { Schemas } from './types';
import type { Misfits } from '../test/misfits';

// The draft API (#36) is on main, so the hand-written types are checked against the generated ones here already
// (R4b spec section 2 left this to the wiring for when the API had merged).
it('draft answer types stay compatible with the generated API fields', () => {
  expectTypeOf<Misfits<DraftAnswer, Schemas['DraftCheckOut']>>().toBeNever();
  expectTypeOf<Misfits<DraftCourse, Schemas['DraftCourse']>>().toBeNever();
  expectTypeOf<Misfits<DraftNotice, Schemas['DraftNoticeOut']>>().toBeNever();
  expectTypeOf<
    Misfits<DraftCandidate, Schemas['DraftCandidateOut']>
  >().toBeNever();
  expectTypeOf<Misfits<DraftResult, Schemas['DraftResult']>>().toBeNever();
  expectTypeOf<Misfits<DraftNode, Schemas['DraftNode']>>().toBeNever();
});

it('the nested rows the component reads are checked through their fields too', () => {
  expectTypeOf<
    Misfits<DraftAnswer['courses'][number], Schemas['DraftCourse']>
  >().toBeNever();
  expectTypeOf<
    Misfits<DraftAnswer['notices'][number], Schemas['DraftNoticeOut']>
  >().toBeNever();
  expectTypeOf<
    Misfits<
      DraftAnswer['notices'][number]['candidates'][number],
      Schemas['DraftCandidateOut']
    >
  >().toBeNever();
  expectTypeOf<
    Misfits<DraftAnswer['result'], Schemas['DraftResult']>
  >().toBeNever();
  expectTypeOf<
    Misfits<DraftAnswer['result']['root'], Schemas['DraftNode']>
  >().toBeNever();
  expectTypeOf<
    Misfits<DraftNode['children'][number], Schemas['DraftNode']>
  >().toBeNever();
});
