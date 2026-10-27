// The program pages on the live API (R4c): /programs lists the programs (R4a's ProgramList) and /programs/<ID> is one
// program's curriculum (R4a's ProgramCurriculum), with the plan chosen in it kept in the shell (ProgramsContext). Old
// links come in through the search page (SearchRoute) and are finished here: a /?program= ref is matched once the list
// reads, and a plan link is checked against the program's answer read fresh.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ApiError, isTransientError } from '../api/client';
import { failureOf, loadOf } from '../api/load';
import type { Load } from '../api/load';
import {
  curriculumQuery,
  policiesQuery,
  programListQuery,
} from '../api/programs';
import { shownData } from '../api/queries';
import { ProgramCurriculum } from '../features/programs/ProgramCurriculum';
import { ProgramList } from '../features/programs/ProgramList';
import { Line } from '../features/programs/ProgramParts';
import { useAccount, viewerScope } from '../layout/account';
import { useProgramsState } from '../layout/ProgramsContext';
import { planRevisions, plansSignature } from '../models/chatPlans';
import { PUBLIC_BASE_URL } from '../models/coursePath';
import { programPath } from '../models/programFormat';
import { match } from '../models/programGuard';
import {
  checkPlanLink,
  matchProgramRef,
  PLAN_LINK_NOTICES,
  programNotFound,
  readPlanLink,
} from '../models/programLinks';
import { parseCurriculum, parseProgramList } from '../models/programs';
import { useOpenCourse } from './SearchRoute';

// R4a's line for a choice cleared because the program's plans changed (ProgramCurriculum), said again where screen
// readers hear it: the line itself is plain text (R4b README, the fourth point for the wiring).
export const PLAN_REVISED_LINE =
  '这个项目的版本化方案有更新，之前选的目录版本与路径已清除，请重新选择。';
export const CHECKING_LINK = '正在核对分享链接里的方案…';
// A program ID as the API takes one (api/routes/program.py); an address with anything else is not asked about.
const PROGRAM_ID = /[a-z0-9][a-z0-9-]{0,63}/;

// What a page was opened with, in its history entry (SearchRoute and this file put it there): a sentence about the
// link, a /?program= ref still to match, the query of a plan link still to check. Anything else there is ignored.
interface LinkState {
  notice?: string;
  programRef?: string;
  planQuery?: string;
}
function linkState(state: unknown): LinkState {
  if (typeof state !== 'object' || state === null) return {};
  const { notice, programRef, planQuery } = state as Record<string, unknown>;
  return {
    ...(typeof notice === 'string' ? { notice } : {}),
    ...(typeof programRef === 'string' ? { programRef } : {}),
    ...(typeof planQuery === 'string' ? { planQuery } : {}),
  };
}

// The pages ask once it is known who is looking, as the search page does: back from Google, nothing but the login is
// asked while the return is being handled (R2b).
function usePageReady() {
  return viewerScope(useAccount()) !== null;
}

// Always there, so what a link came to is heard when it appears.
function LinkNotice({ text }: { text: string | undefined }) {
  return (
    <div role="status" aria-label="分享链接">
      {text !== undefined && <Line kind="info">{text}</Line>}
    </div>
  );
}

export function ProgramsRoute() {
  const ready = usePageReady();
  const programs = useQuery({ ...programListQuery, enabled: ready });
  const navigate = useNavigate();
  const { state } = useLocation();
  const { notice, programRef } = linkState(state);
  const body = shownData(programs);
  const rows = useMemo(() => {
    if (body === undefined) return null;
    const parsed = parseProgramList(body);
    return parsed.kind === 'ok' ? parsed.data : null;
  }, [body]);
  // A /?program= ref, once the list reads: the program it names, or the list with a sentence. While the list cannot be
  // read the list says so and offers to load it again; the ref waits for it.
  useEffect(() => {
    if (programRef === undefined || rows === null) return;
    const id = matchProgramRef(programRef, rows);
    void navigate(id === null ? '/programs' : programPath(id), {
      replace: true,
      state: id === null ? { notice: programNotFound(programRef) } : null,
    });
  }, [programRef, rows, navigate]);
  // Loading again takes the pressed button away: focus goes to the list, as in R4a's demo.
  const view = useRef<HTMLElement>(null);
  const [retried, setRetried] = useState(0);
  useEffect(() => {
    if (retried > 0) view.current?.focus({ preventScroll: true });
  }, [retried]);
  return (
    <>
      <LinkNotice text={notice} />
      <ProgramList
        ref={view}
        programs={loadOf(programs)}
        onOpenProgram={(id) => void navigate(programPath(id))}
        onRetry={() => {
          void programs.refetch();
          setRetried((n) => n + 1);
        }}
      />
    </>
  );
}

// Policy evidence as it is read now: a read on its way shows as loading even while an earlier answer is still held, so
// the evidence shown is never an old one (R0 14.10).
function freshLoad(query: {
  data: unknown;
  error: unknown;
  isError: boolean;
  isFetching: boolean;
}): Load {
  if (query.isFetching) return { status: 'loading' };
  if (query.isError)
    return { status: 'failed', failure: failureOf(query.error) };
  return query.data === undefined
    ? { status: 'loading' }
    : { status: 'ready', data: query.data };
}

function codeOf(
  parsed: ReturnType<typeof parseCurriculum> | null,
  courseId: string,
) {
  if (parsed?.kind !== 'ok') return null;
  for (const group of parsed.data.semesters)
    for (const course of group.courses)
      if (course.course_id === courseId) return course.primary_code;
  return null;
}

export function ProgramRoute() {
  const { programId = '' } = useParams();
  const valid = match(PROGRAM_ID, programId);
  const ready = usePageReady();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const openCourse = useOpenCourse();
  const programs = useProgramsState();
  const curriculum = useQuery({
    ...curriculumQuery(programId),
    enabled: ready && valid,
  });
  const body = shownData(curriculum);
  const parsed = body === undefined ? null : parseCurriculum(body, programId);
  const revisions = useMemo(
    () => (body === undefined ? {} : planRevisions(body)),
    [body],
  );
  const planId = programs.chosenPlan(programId);
  const revision =
    planId !== null && Object.hasOwn(revisions, planId)
      ? revisions[planId]!
      : '';
  const policies = useQuery({
    ...policiesQuery(programId, planId ?? '', revision),
    enabled: ready && valid && planId !== null,
  });

  // A plan link, checked once against the program's answer read fresh (Streamlit reads it past the cache too): exactly
  // the plan shared is chosen, or nothing is and the page says why. A failure only for a moment leaves it to the next
  // read of the program that succeeds (「刷新方案及政策证据」 asks again).
  const { notice, planQuery } = linkState(location.state);
  const link = useMemo(() => {
    const read =
      planQuery === undefined
        ? null
        : readPlanLink(new URLSearchParams(planQuery));
    return read !== null && read.program_id === programId ? read : null;
  }, [planQuery, programId]);
  const [retrying, setRetrying] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const { pathname } = location;
  const settle = useCallback(
    (fresh: unknown) => {
      if (link === null || !alive.current) return;
      const status = checkPlanLink(fresh, link);
      if (status === 'ready')
        programs.choosePlan(programId, link.plan_id, plansSignature(fresh));
      setRetrying(false);
      void navigate(pathname, {
        replace: true,
        state: { notice: PLAN_LINK_NOTICES[status] },
      });
    },
    [link, navigate, pathname, programId, programs],
  );
  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (link === null || !ready || handled.current === location.key) return;
    handled.current = location.key;
    // The linked program's earlier choice goes first, as in Streamlit.
    programs.forget(programId);
    queryClient
      .fetchQuery({ ...curriculumQuery(programId), staleTime: 0 })
      .then(settle, (error: unknown) => {
        if (!alive.current) return;
        if (isTransientError(error)) {
          setRetrying(true);
          return;
        }
        // The program is not there (the page says so) or cannot be read as it is.
        void navigate(pathname, {
          replace: true,
          state:
            error instanceof ApiError && error.status === 404
              ? null
              : { notice: PLAN_LINK_NOTICES.unavailable },
        });
      });
  }, [
    link,
    ready,
    location.key,
    programs,
    programId,
    queryClient,
    settle,
    navigate,
    pathname,
  ]);
  // The failed read left the program's query in error, its older answer kept; only a read that succeeds after it puts
  // the query back to success.
  useEffect(() => {
    if (retrying && curriculum.isSuccess) settle(curriculum.data);
  }, [retrying, curriculum.isSuccess, curriculum.data, settle]);

  const said =
    link === null ? notice : retrying ? PLAN_LINK_NOTICES.retry : CHECKING_LINK;
  return (
    <>
      <LinkNotice text={said} />
      <p role="status" aria-label="方案更新" className="visually-hidden">
        {programs.planRevised(programId) ? PLAN_REVISED_LINE : ''}
      </p>
      <ProgramCurriculum
        programId={programId}
        curriculum={
          valid
            ? loadOf(curriculum)
            : { status: 'failed', failure: failureOf(new ApiError(404)) }
        }
        planRevisions={revisions}
        selectedPlanId={planId}
        onSelectPlan={(id) =>
          programs.choosePlan(
            programId,
            id,
            body === undefined ? '' : plansSignature(body),
          )
        }
        planRevised={programs.planRevised(programId)}
        policies={planId === null ? null : freshLoad(policies)}
        publicBaseUrl={PUBLIC_BASE_URL}
        onBack={() => void navigate('/programs')}
        onRefresh={() => {
          programs.forget(programId);
          // The program's answer goes from the cache, so a failed read shows no older curriculum (Streamlit deletes it);
          // the page reads it again at once.
          void queryClient.resetQueries({
            queryKey: curriculumQuery(programId).queryKey,
            exact: true,
          });
        }}
        onViewCourse={(courseId) =>
          openCourse(courseId, codeOf(parsed, courseId) ?? courseId)
        }
      />
    </>
  );
}
