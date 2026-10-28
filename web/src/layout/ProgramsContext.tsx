// The program pages' state (R4c), kept above the pages like the search page's (SearchContext): the plan chosen in each
// program, as Streamlit keeps one choice per program (program-plan-{id}) through a visit elsewhere; what the page says
// about a choice that went, or one a shared link made; and the course draft (R4b's PlanDraft). The program itself is
// in the address (/programs/<ID>). Apart from the search page's choice, as in Streamlit (the user's choice, 10-27);
// the two share only the curriculum cache. It belongs to who is looking: a logout, an account deletion or another
// person's login empties it, as Streamlit's logout sets every program's plan choice to None and clears the draft. It
// lives in this tab's memory only: the draft goes to the API's check and nowhere else, no address, storage or question.
import { useQueries, useQueryClient } from '@tanstack/react-query';
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
import { checkDraft } from '../api/draft';
import { failureOf } from '../api/load';
import type { ApiFailure } from '../api/load';
import { curriculumQuery } from '../api/programs';
import { shownData } from '../api/queries';
import { plansSignature } from '../models/chatPlans';
import { parseDraftAnswer, planGone } from '../models/planDraft';
import { availablePlans } from '../models/programPlans';
import { parseCurriculum } from '../models/programs';

interface Choice {
  planId: string;
  // The program's plan list when the plan was chosen (plansSignature).
  signature: string;
}
// What the page says about the choice: R4a's line that the plans were updated, or R4b's that the plan cannot be used
// (the draft check refused it, and the plans read again had not changed), both about a choice that went; or that a
// shared link chose it, said while it stays chosen (a reload keeps the link's history entry, not the choice).
type Notice = 'revised' | 'refused' | 'linked';

// A plan the page shows the draft under: the program, the plan, the content version the page shows for it
// (planRevisions) and the plan list it is in (plansSignature).
export interface DraftPlan {
  programId: string;
  planId: string;
  revision: string;
  signature: string;
}
// What PlanDraft shows under a plan: the last answer and the last failure of the checks for it, and whether one is on
// its way. Each stays the same object until the next check's outcome, so the component knows a new one (R4b README,
// the third point for the wiring).
export interface DraftView {
  answer: unknown;
  checking: boolean;
  failure: ApiFailure | null;
}
const NO_DRAFT: DraftView = { answer: null, checking: false, failure: null };
// The view of the checks under the plan of the last one.
interface Shown {
  plan: DraftPlan | null;
  view: DraftView;
}
const NOTHING: Shown = { plan: null, view: NO_DRAFT };
const samePlan = (a: DraftPlan | null, b: DraftPlan) =>
  a !== null &&
  a.programId === b.programId &&
  a.planId === b.planId &&
  a.revision === b.revision;

export interface ProgramsState {
  // The plan chosen in this program, or null.
  chosenPlan: (programId: string) => string | null;
  // The program's plans changed under the choice, which went (R4a's line that the plans were updated), until the next
  // choice or refresh.
  planRevised: (programId: string) => boolean;
  // The draft check refused the chosen plan, which went, and the plans read again had not changed (R4b's sentence
  // for it), until the next choice or refresh.
  planRefused: (programId: string) => boolean;
  // A shared link chose the plan chosen now (the link's sentence that it did), until the next choice or refresh.
  planLinked: (programId: string) => boolean;
  // signature: plansSignature of the answer the choice was made from; linked: a shared link chose it. A check on its
  // way in the program stops unless this is the choice it was sent under: what it comes to is not this choice's.
  choosePlan: (
    programId: string,
    planId: string | null,
    signature: string,
    linked?: boolean,
  ) => void;
  // The choice and the notice go: 「刷新方案及政策证据」 (Streamlit sets the choice to None and says nothing) and a plan
  // link being checked. A draft checked under the program's plan is checked again when the page next shows it.
  forget: (programId: string) => void;
  // The draft: one per tab, across programs and plans, as Streamlit's plan_draft_courses is one per session. When
  // someone else is looking it is emptied with the choices, so PlanDraft goes and its typed text with it.
  draftView: (plan: DraftPlan) => DraftView;
  // The page shows the draft under this plan: it is checked there with its courses and no text, so its count and
  // rule tree are there from the start, as Streamlit draws them for an empty draft. Not again under the plan of the
  // last check.
  showDraft: (plan: DraftPlan) => void;
  addToDraft: (plan: DraftPlan, text: string) => void;
  removeFromDraft: (plan: DraftPlan, courseId: string) => void;
  clearDraft: (plan: DraftPlan) => void;
  retryDraft: (plan: DraftPlan) => void;
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
  const queryClient = useQueryClient();
  const [choices, setChoices] = useState<Readonly<Record<string, Choice>>>({});
  const [notices, setNotices] = useState<Readonly<Record<string, Notice>>>({});
  const [shown, setShown] = useState<Shown>(NOTHING);
  // The draft's course IDs for the next check: the answer's after each check whose answer reads for its plan, and at
  // once after a removal or clearing. Never drawn from here: the component shows the answer's.
  const courses = useRef<readonly string[]>([]);
  // The last check: its plan, its text (重新核对 sends it again), its number and how to stop it. A later check, a
  // refresh of its program or another person looking makes its outcome count for nothing.
  const sent = useRef<{
    plan: DraftPlan | null;
    input: string | undefined;
    seq: number;
    stop: AbortController | null;
  }>({ plan: null, input: undefined, seq: 0, stop: null });
  // Programs whose plan the draft check refused, with the number of the read that decides what the page says; a
  // choice, a refresh or another person looking since takes it off.
  const refusals = useRef(new Map<string, number>());
  const refusalSeq = useRef(0);

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
    if (changed.length > 0) {
      const said = { ...notices };
      for (const id of changed) said[id] = 'revised';
      setNotices(said);
    }
  }

  // The outcome of the check on its way no longer counts, and the request stops.
  const drop = useCallback(() => {
    sent.current.seq += 1;
    sent.current.stop?.abort();
    sent.current.stop = null;
    sent.current.plan = null;
  }, []);

  // Another person, or nobody, is looking now: what the last one chose and drafted goes. The first answer of /auth/me
  // only says who it was all along.
  const last = useRef(owner);
  useEffect(() => {
    if (owner === undefined) return;
    if (last.current !== undefined && last.current !== owner) {
      setChoices({});
      setNotices({});
      refusals.current.clear();
      drop();
      courses.current = [];
      // Not shown again (the next check sends its own), but the words the last person typed do not stay in memory.
      sent.current.input = undefined;
      setShown(NOTHING);
    }
    last.current = owner;
  }, [owner, drop]);

  // 409 missing, stale, draft or unusable: the plan is not there to check the draft against (R4b spec section 8). The
  // choice goes at once, the draft's courses stay, and the program is read again past the cache (Streamlit lets the
  // curriculum go stale after a refused plan): plans that changed say R4a's line, unchanged ones, or none read, R4b's.
  // A read the program page stops reading (the student left it) is stopped by TanStack and counts as none read.
  // The refused plan is still the choice, or none is left: any other choice in the program stopped the check
  // (choosePlan), so its refusal is never said of a plan chosen since.
  const refuse = useCallback(
    (plan: DraftPlan) => {
      const { programId } = plan;
      setChoices((current) =>
        Object.hasOwn(current, programId) &&
        current[programId]!.planId === plan.planId &&
        current[programId]!.signature === plan.signature
          ? omit(current, programId)
          : current,
      );
      const token = (refusalSeq.current += 1);
      refusals.current.set(programId, token);
      const settle = (notice: Notice) => {
        if (refusals.current.get(programId) !== token) return;
        refusals.current.delete(programId);
        setNotices((current) => ({ ...current, [programId]: notice }));
      };
      queryClient
        .fetchQuery({ ...curriculumQuery(programId), staleTime: 0 })
        .then(
          (fresh) =>
            settle(
              plansSignature(fresh) === plan.signature ? 'refused' : 'revised',
            ),
          () => settle('refused'),
        );
    },
    [queryClient],
  );

  // Every check goes through here. The last one counts: one still on its way is stopped and its outcome dropped
  // (R4b README, the first point for the wiring). fresh: the answer and failure before it go at once (清空).
  const send = useCallback(
    (
      plan: DraftPlan,
      list: readonly string[],
      input: string | undefined,
      fresh: boolean,
    ) => {
      sent.current.stop?.abort();
      const seq = sent.current.seq + 1;
      const stop = new AbortController();
      sent.current = { plan, input, seq, stop };
      courses.current = list;
      // Under another plan the last answer and failure go at once: they are not this plan's (R4b README, the second
      // point).
      setShown((current) => {
        const kept = !fresh && samePlan(current.plan, plan);
        return {
          plan,
          view: {
            answer: kept ? current.view.answer : null,
            failure: kept ? current.view.failure : null,
            checking: true,
          },
        };
      });
      checkDraft(
        plan.programId,
        plan.planId,
        {
          plan_content_sha256: plan.revision,
          course_ids: [...list],
          ...(input === undefined ? {} : { input }),
        },
        stop.signal,
      ).then(
        (answer) => {
          if (sent.current.seq !== seq) return;
          sent.current.stop = null;
          // The draft is what the server stands behind, when its answer can be shown for this plan.
          const read = parseDraftAnswer(answer);
          if (
            read.kind === 'ok' &&
            read.answer.plan_content_sha256 === plan.revision
          )
            courses.current = read.answer.courses.map((c) => c.course_id);
          setShown({ plan, view: { answer, failure: null, checking: false } });
        },
        (error: unknown) => {
          if (sent.current.seq !== seq) return;
          sent.current.stop = null;
          const failure = failureOf(error);
          // These never reach the component, which goes with the choice (R4b spec section 8). The check goes with its
          // outcome, so the plan chosen again is checked again there (review A33).
          if (planGone(failure)) {
            sent.current.plan = null;
            setShown(NOTHING);
            refuse(plan);
            return;
          }
          setShown((current) => ({
            plan,
            view: { ...current.view, failure, checking: false },
          }));
        },
      );
    },
    [refuse],
  );

  const chosenPlan = useCallback(
    (programId: string) =>
      Object.hasOwn(choices, programId) ? choices[programId]!.planId : null,
    [choices],
  );
  const planRevised = useCallback(
    (programId: string) =>
      Object.hasOwn(notices, programId) && notices[programId] === 'revised',
    [notices],
  );
  const planRefused = useCallback(
    (programId: string) =>
      Object.hasOwn(notices, programId) && notices[programId] === 'refused',
    [notices],
  );
  // Only while the choice the link made is there: the plans read again, or a refusal, can take it first.
  const planLinked = useCallback(
    (programId: string) =>
      Object.hasOwn(notices, programId) &&
      notices[programId] === 'linked' &&
      Object.hasOwn(choices, programId),
    [notices, choices],
  );
  const choosePlan = useCallback(
    (
      programId: string,
      planId: string | null,
      signature: string,
      linked = false,
    ) => {
      const last = sent.current;
      if (
        last.stop !== null &&
        last.plan?.programId === programId &&
        (last.plan.planId !== planId || last.plan.signature !== signature)
      )
        drop();
      setChoices((current) =>
        planId === null
          ? omit(current, programId)
          : { ...current, [programId]: { planId, signature } },
      );
      setNotices((current) =>
        linked
          ? { ...current, [programId]: 'linked' }
          : omit(current, programId),
      );
      refusals.current.delete(programId);
    },
    [drop],
  );
  const forget = useCallback(
    (programId: string) => {
      setChoices((current) => omit(current, programId));
      setNotices((current) => omit(current, programId));
      refusals.current.delete(programId);
      // The plans are read again, so is the draft under them (Streamlit works it out on every run); its courses stay.
      if (sent.current.plan?.programId === programId) {
        drop();
        setShown(NOTHING);
      }
    },
    [drop],
  );

  const draftView = useCallback(
    (plan: DraftPlan): DraftView =>
      samePlan(shown.plan, plan) ? shown.view : NO_DRAFT,
    [shown],
  );
  const showDraft = useCallback(
    (plan: DraftPlan) => {
      if (!samePlan(sent.current.plan, plan))
        send(plan, courses.current, undefined, false);
    },
    [send],
  );
  const addToDraft = useCallback(
    (plan: DraftPlan, text: string) => send(plan, courses.current, text, false),
    [send],
  );
  // While a check is on its way too: the rest is sent at once, and that check is the one that counts.
  const removeFromDraft = useCallback(
    (plan: DraftPlan, courseId: string) =>
      send(
        plan,
        courses.current.filter((id) => id !== courseId),
        undefined,
        false,
      ),
    [send],
  );
  // 清空: the draft and its answer go at once, without a request of their own; then the empty draft is checked, as
  // when a plan is chosen.
  const clearDraft = useCallback(
    (plan: DraftPlan) => send(plan, [], undefined, true),
    [send],
  );
  const retryDraft = useCallback(
    (plan: DraftPlan) => send(plan, courses.current, sent.current.input, false),
    [send],
  );

  const value = useMemo<ProgramsState>(
    () => ({
      chosenPlan,
      planRevised,
      planRefused,
      planLinked,
      choosePlan,
      forget,
      draftView,
      showDraft,
      addToDraft,
      removeFromDraft,
      clearDraft,
      retryDraft,
    }),
    [
      chosenPlan,
      planRevised,
      planRefused,
      planLinked,
      choosePlan,
      forget,
      draftView,
      showDraft,
      addToDraft,
      removeFromDraft,
      clearDraft,
      retryDraft,
    ],
  );
  return (
    <ProgramsContext.Provider value={value}>
      {children}
    </ProgramsContext.Provider>
  );
}

function omit<T>(
  record: Readonly<Record<string, T>>,
  key: string,
): Readonly<Record<string, T>> {
  if (!Object.hasOwn(record, key)) return record;
  const next = { ...record };
  delete next[key];
  return next;
}

export function useProgramsState(): ProgramsState {
  const value = useContext(ProgramsContext);
  if (!value) throw new Error('ProgramsProvider is required');
  return value;
}
