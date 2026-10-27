// The program pages' state (R4c), kept above the pages like the search page's (SearchContext): the plan chosen in each
// program, as Streamlit keeps one choice per program (program-plan-{id}) through a visit elsewhere, and whether that
// program's plans changed under the choice. The program itself is in the address (/programs/<ID>). Apart from the
// search page's choice, as in Streamlit (the user's choice, 10-27); the two share only the curriculum cache. It belongs
// to who is looking: a logout, an account deletion or another person's login empties it, as Streamlit's logout sets
// every program's plan choice to None. It lives in this tab's memory only.
import { useQueries } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { curriculumQuery } from '../api/programs';
import { shownData } from '../api/queries';
import { plansSignature } from '../models/chatPlans';
import { availablePlans } from '../models/programPlans';
import { parseCurriculum } from '../models/programs';

interface Choice {
  planId: string;
  // The program's plan list when the plan was chosen (plansSignature).
  signature: string;
}

export interface ProgramsState {
  // The plan chosen in this program, or null.
  chosenPlan: (programId: string) => string | null;
  // The program's plans changed under the choice, which went (R4a's line that the plans were updated), until the next
  // choice or refresh.
  planRevised: (programId: string) => boolean;
  // signature: plansSignature of the answer the choice was made from.
  choosePlan: (
    programId: string,
    planId: string | null,
    signature: string,
  ) => void;
  // The choice and the notice go: 「刷新方案及政策证据」 (Streamlit sets the choice to None and says nothing) and a plan
  // link being checked.
  forget: (programId: string) => void;
}

// Exported for tests that give a page a state of their own.
export const ProgramsContext = createContext<ProgramsState | null>(null);

export function ProgramsProvider({
  owner,
  children,
}: {
  // viewerOwner() of who is looking, or undefined while that is not known yet.
  owner: string | undefined;
  children: ReactNode;
}) {
  const [choices, setChoices] = useState<Readonly<Record<string, Choice>>>({});
  const [revised, setRevised] = useState<ReadonlySet<string>>(new Set());

  // The pages ask for each program's curriculum; this only reads the answers of the programs with a choice.
  const ids = Object.keys(choices);
  const reads = useQueries({
    queries: ids.map((id) => ({ ...curriculumQuery(id), enabled: false })),
  });
  // A choice whose program's plan list changed goes, and the page says so once (Streamlit compares the plans before and
  // after a read); one whose plan is no longer offered goes without a word (app/program_plan_view.py). Put right while
  // rendering, the way React adjusts state to a value that changed, so nothing is drawn with the stale choice, and a
  // list that changes back cannot bring the old choice back.
  const changed: string[] = [];
  const gone: string[] = [];
  ids.forEach((id, index) => {
    const body = shownData(reads[index]!);
    if (body === undefined) return;
    const choice = choices[id]!;
    if (plansSignature(body) !== choice.signature) changed.push(id);
    else {
      const parsed = parseCurriculum(body, id);
      if (
        parsed.kind !== 'ok' ||
        !availablePlans(parsed.data.plans, id).plans.some(
          (plan) => plan.plan_id === choice.planId,
        )
      )
        gone.push(id);
    }
  });
  if (changed.length > 0 || gone.length > 0) {
    const next = { ...choices };
    for (const id of [...changed, ...gone]) delete next[id];
    setChoices(next);
    if (changed.length > 0) setRevised(new Set([...revised, ...changed]));
  }

  // Another person, or nobody, is looking now: what the last one chose goes. The first answer of /auth/me only says who
  // it was all along.
  const last = useRef(owner);
  useEffect(() => {
    if (owner === undefined) return;
    if (last.current !== undefined && last.current !== owner) {
      setChoices({});
      setRevised(new Set());
    }
    last.current = owner;
  }, [owner]);

  const chosenPlan = useCallback(
    (programId: string) =>
      Object.hasOwn(choices, programId) ? choices[programId]!.planId : null,
    [choices],
  );
  const planRevised = useCallback(
    (programId: string) => revised.has(programId),
    [revised],
  );
  const choosePlan = useCallback(
    (programId: string, planId: string | null, signature: string) => {
      setChoices((current) => {
        const next = { ...current };
        if (planId === null) delete next[programId];
        else next[programId] = { planId, signature };
        return next;
      });
      setRevised((current) => without(current, programId));
    },
    [],
  );
  const forget = useCallback((programId: string) => {
    setChoices((current) => {
      if (!Object.hasOwn(current, programId)) return current;
      const next = { ...current };
      delete next[programId];
      return next;
    });
    setRevised((current) => without(current, programId));
  }, []);

  const value = useMemo<ProgramsState>(
    () => ({ chosenPlan, planRevised, choosePlan, forget }),
    [chosenPlan, planRevised, choosePlan, forget],
  );
  return (
    <ProgramsContext.Provider value={value}>
      {children}
    </ProgramsContext.Provider>
  );
}

function without(set: ReadonlySet<string>, item: string): ReadonlySet<string> {
  if (!set.has(item)) return set;
  const next = new Set(set);
  next.delete(item);
  return next;
}

export function useProgramsState(): ProgramsState {
  const value = useContext(ProgramsContext);
  if (!value) throw new Error('ProgramsProvider is required');
  return value;
}
