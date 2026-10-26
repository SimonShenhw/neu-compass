// The search page's state (R3e), kept above the pages so the conversation and the choices outlive a visit to a course
// page and back (R0 3 ③): the conversation (R3c's useConversation), the program and plan a question is asked under,
// and the opt-in to save answers. It belongs to who is looking: a logout, an account deletion or another person's
// login empties it, as Streamlit's logout clears the conversation, the program and plan choices and the opt-in
// (app/state_manager.py). It lives in this tab's memory only.
import { useQuery, useQueryClient } from '@tanstack/react-query';
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
import type { ChatSource } from '../api/chat';
import { streamChat } from '../api/chatStream';
import type { ChatRequest } from '../api/chatStream';
import { ApiError } from '../api/client';
import { curriculumQuery } from '../api/programs';
import { configQuery, shownData } from '../api/queries';
import { useConversation } from '../features/search-answer/useConversation';
import { chatPlans, planSelection, plansSignature } from '../models/chatPlans';
import type { ChatPlan } from '../models/chatPlans';
import type { Turn } from '../models/chatTurn';
import { contextCourseIds, recentHistory } from '../models/conversation';

// The API takes a question of 1 to 500 characters (api/models.py); the ask box says so instead of sending one longer.
export const MAX_QUESTION_CHARS = 500;
export const questionLength = (text: string) => Array.from(text).length;
// Streamlit always asks for 10 courses (R0 3 ②).
const RESULTS = 10;
// The refusals that mean the plan chosen is not the one the server has now: the choice goes and the program's plans
// are asked again, as Streamlit's queue_chat_plan_reset does. A program conflict keeps the choice (R0 3 ③).
const PLAN_REFUSALS = new Set([
  'plan_missing',
  'plan_stale',
  'plan_draft',
  'plan_unusable',
  'plan_unavailable',
]);

export interface SearchState {
  turns: readonly Turn[];
  busy: boolean;
  ask: (question: string) => void;
  programId: string | null;
  chooseProgram: (programId: string | null) => void;
  // What this program offers for a question, and the plan chosen; null when none is, or the list changed under it.
  plans: readonly ChatPlan[];
  plan: ChatPlan | null;
  choosePlan: (planId: string | null) => void;
  // The program's plans changed since the choice, which went (Streamlit's 方案有更新 caption), until the next choice.
  planRevised: boolean;
  // The program's plan list cannot be read now, so no plan goes with a question (Streamlit's 暂时无法核对方案列表).
  plansUnavailable: boolean;
  allowSave: boolean;
  setAllowSave: (allow: boolean) => void;
  // /config's answer_feedback_enabled; null until /config has answered.
  feedback: boolean | null;
}

// Exported for tests that give a component a search state of their own.
export const SearchContext = createContext<SearchState | null>(null);

// R2b's stream; a plan refusal is handled before the conversation shows R3c's sentence for it.
function chatSource(request: ChatRequest, planRefused: () => void): ChatSource {
  return async function* source(signal) {
    try {
      yield* streamChat(request, { signal });
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        PLAN_REFUSALS.has(error.reason ?? '')
      )
        planRefused();
      throw error;
    }
  };
}

interface Choice {
  planId: string;
  // The program's plan list when the plan was chosen (plansSignature).
  signature: string;
}

export function SearchProvider({
  owner,
  children,
}: {
  // viewerOwner() of who is looking, or undefined while that is not known yet.
  owner: string | undefined;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const { turns, busy, ask: askWith, reset } = useConversation();
  const [programId, setProgramId] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [planRevised, setPlanRevised] = useState(false);
  const [allowSave, setAllowSave] = useState(false);
  // useSession asks /config (holding it back while the address carries Google's code); this only reads its answer.
  const config = useQuery({ ...configQuery, enabled: false });
  const feedback = shownData(config)?.answer_feedback_enabled ?? null;
  const feedbackEnabled = feedback === true;
  const curriculum = useQuery({
    ...curriculumQuery(programId ?? ''),
    enabled: programId !== null,
  });
  const body = programId === null ? undefined : shownData(curriculum);
  const plans = useMemo(
    () =>
      body === undefined || programId === null
        ? []
        : chatPlans(body, programId),
    [body, programId],
  );
  const signature = body === undefined ? null : plansSignature(body);
  const plan =
    choice !== null && signature === choice.signature
      ? (plans.find((p) => p.plan.plan_id === choice.planId) ?? null)
      : null;
  const listGone =
    programId !== null && body === undefined && curriculum.isError;

  // The list changed under the choice, so it goes and the page says so once; a list that can no longer be read takes
  // the choice with it, as Streamlit's does (暂时无法核对方案列表；未携带方案). Put right while rendering, the way React
  // adjusts state to a value that changed, so nothing is drawn with the stale choice.
  if (choice !== null && plan === null && (signature !== null || listGone)) {
    setChoice(null);
    if (signature !== null) setPlanRevised(true);
  }

  // Another person, or nobody, is looking now: what the last one asked and chose goes. The first answer of /auth/me
  // only says who it was all along.
  const last = useRef(owner);
  useEffect(() => {
    if (owner === undefined) return;
    if (last.current !== undefined && last.current !== owner) {
      reset();
      setProgramId(null);
      setChoice(null);
      setPlanRevised(false);
      setAllowSave(false);
    }
    last.current = owner;
  }, [owner, reset]);

  // Streamlit clears the opt-in while answer feedback is off (put right while rendering, as above), so it is never
  // ticked then, whatever was set, and no question asks to save its answer.
  if (!feedbackEnabled && allowSave) setAllowSave(false);

  const chooseProgram = useCallback((id: string | null) => {
    setProgramId(id);
    setChoice(null);
    setPlanRevised(false);
  }, []);
  const choosePlan = useCallback(
    (id: string | null) => {
      setPlanRevised(false);
      setChoice(
        id === null || signature === null ? null : { planId: id, signature },
      );
    },
    [signature],
  );

  const ask = useCallback(
    (question: string) => {
      const query = question.trim();
      if (query === '' || questionLength(query) > MAX_QUESTION_CHARS) return;
      const asked = programId;
      const refused = plan?.plan.plan_id ?? null;
      const request: ChatRequest = {
        query,
        k: RESULTS,
        allow_feedback_capture: allowSave,
        history: recentHistory(turns),
        context_course_ids: contextCourseIds(turns),
        ...(asked === null ? {} : { program_id: asked }),
        ...(plan === null ? {} : { plan: planSelection(plan) }),
      };
      askWith({
        question: query,
        allowSave,
        source: chatSource(request, () => {
          // Only the plan that was refused: a choice made since stays.
          setChoice((current) =>
            current !== null && current.planId === refused ? null : current,
          );
          if (asked !== null)
            void queryClient.invalidateQueries({
              queryKey: curriculumQuery(asked).queryKey,
            });
        }),
      });
    },
    [allowSave, askWith, plan, programId, queryClient, turns],
  );

  const value = useMemo<SearchState>(
    () => ({
      turns,
      busy,
      ask,
      programId,
      chooseProgram,
      plans,
      plan,
      choosePlan,
      planRevised,
      plansUnavailable: listGone,
      allowSave,
      setAllowSave,
      feedback,
    }),
    [
      turns,
      busy,
      ask,
      programId,
      chooseProgram,
      plans,
      plan,
      choosePlan,
      planRevised,
      listGone,
      allowSave,
      feedback,
    ],
  );
  return (
    <SearchContext.Provider value={value}>{children}</SearchContext.Provider>
  );
}

export function useSearch(): SearchState {
  const value = useContext(SearchContext);
  if (!value) throw new Error('SearchProvider is required');
  return value;
}
