// The search page on the live API (R3e): the program and plan a question is asked under, R3d's landing until the
// first question, then R3c's conversation, with what it needs from the shell's search state (layout/SearchContext).
// A course page (CourseRoute) shows the same column beside the course.
import { useQueries, useQuery } from '@tanstack/react-query';
import { Info } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import {
  Link,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom';
import { coopListQuery } from '../api/coop';
import { sendFeedback } from '../api/feedback';
import { loadOf } from '../api/load';
import { isLoginReturn } from '../api/login';
import { curriculumQuery, programListQuery } from '../api/programs';
import { shownData } from '../api/queries';
import { Select } from '../components/Select';
import { SearchConversation } from '../features/search-answer/SearchConversation';
import { SearchLanding } from '../features/search-landing/SearchLanding';
import { useAccount, viewerScope } from '../layout/account';
import { useSearch } from '../layout/SearchContext';
import { oneLine } from '../models/courseDetailFormat';
import { coursePath } from '../models/coursePath';
import { FEATURED_PROGRAM_IDS, showLanding } from '../models/landing';
import { PLAN_PLACEHOLDER, scopeLabel } from '../models/programFormat';
import { parseCurriculum, parseProgramList } from '../models/programs';
import styles from './SearchPage.module.css';

const NONE = '__none__';
// Streamlit's words for the two selectors (app/program_plan_view.py, app/chat_plan_view.py); R3c's failure lines name
// them 「项目」 and 「方案」.
export const PROGRAMS_UNAVAILABLE = '暂时无法加载项目列表；课程搜索仍可使用。';
export const PROGRAM_NOTE =
  '只用来区分项目；校区、Catalog 年份和你个人的要求仍需要自己核实。';
export const PLANS_UNAVAILABLE =
  '暂时无法核对方案列表；未携带方案，课程搜索仍可使用。';
export const PLAN_REVISED =
  '方案有更新，之前的方案版本选择已清除，请重新明确选择。';
export const PLAN_NOTE =
  '只按你选的方案解释规则；不判断你是否适用、能否注册或毕业。';

// A course link opens its page; the course ID goes along when it is known, so the page need not resolve the code.
export function useOpenCourse() {
  const navigate = useNavigate();
  return (courseId: string | null, code: string) =>
    void navigate(coursePath(code), {
      state: courseId === null ? null : { courseId },
    });
}

// This page's requests go out once it is known who is looking: back from Google, nothing but the login is asked while
// the return is being handled (R2b), and on a normal load /auth/me answers in a moment.
function usePrograms() {
  const ready = viewerScope(useAccount()) !== null;
  return useQuery({ ...programListQuery, enabled: ready });
}

function ProgramChoice() {
  const search = useSearch();
  const programs = usePrograms();
  const parsed = (() => {
    const body = shownData(programs);
    return body === undefined ? null : parseProgramList(body);
  })();
  const rows = parsed?.kind === 'ok' ? parsed.data : null;
  const { programId, chooseProgram } = search;
  // A program no longer in the list goes, as in Streamlit (app/program_plan_view.py).
  useEffect(() => {
    if (
      rows !== null &&
      programId !== null &&
      !rows.some((row) => row.program_id === programId)
    )
      chooseProgram(null);
  }, [rows, programId, chooseProgram]);
  if (rows === null)
    return programs.isError && !programs.isFetching ? (
      <p className={styles.hint}>{PROGRAMS_UNAVAILABLE}</p>
    ) : null;
  if (rows.length === 0) return null;
  return (
    <div role="group" className={styles.choices} aria-label="项目和方案">
      <div className={styles.context}>
        <Select
          label="项目"
          value={programId ?? NONE}
          onChange={(value) => chooseProgram(value === NONE ? null : value)}
          options={[
            { value: NONE, label: '不指定' },
            ...rows.map((row) => ({
              value: row.program_id,
              label: `${oneLine(row.full_name)} · ${row.program_id}`,
            })),
          ]}
        />
        {programId !== null && search.plans.length > 0 && (
          <Select
            label="方案"
            value={search.plan?.plan.plan_id ?? NONE}
            onChange={(value) =>
              search.choosePlan(value === NONE ? null : value)
            }
            options={[
              { value: NONE, label: PLAN_PLACEHOLDER },
              ...search.plans.map(({ plan }) => ({
                value: plan.plan_id,
                label: scopeLabel(plan),
              })),
            ]}
          />
        )}
      </div>
      {programId !== null && (
        <p className={styles.hint}>
          <Info aria-hidden="true" />
          {search.plan === null ? PROGRAM_NOTE : PLAN_NOTE}
        </p>
      )}
      {search.plansUnavailable && (
        <p className={styles.hint}>{PLANS_UNAVAILABLE}</p>
      )}
      {search.planRevised && <p className={styles.hint}>{PLAN_REVISED}</p>}
    </div>
  );
}

function SearchColumn() {
  const search = useSearch();
  const account = useAccount();
  const navigate = useNavigate();
  const openCourse = useOpenCourse();
  const landing = showLanding(search.turns);
  const programs = usePrograms();
  const listed = (() => {
    const body = shownData(programs);
    const parsed = body === undefined ? null : parseProgramList(body);
    return parsed?.kind === 'ok' ? parsed.data : [];
  })();
  // Only the featured programs the list has, and only while the landing shows (R3d spec 2).
  const featured = landing
    ? FEATURED_PROGRAM_IDS.filter((id) =>
        listed.some((row) => row.program_id === id),
      )
    : [];
  const curricula = useQueries({
    queries: featured.map((id) => curriculumQuery(id)),
  });
  const scope = viewerScope(account);
  const coop = useQuery({
    ...coopListQuery(scope ?? 'pending'),
    enabled: landing && scope !== null,
  });
  // From the landing into the conversation, the button pressed is gone with the landing: focus goes to the
  // conversation, without scrolling (R3d spec 3; the focus rule of 10-25).
  const region = useRef<HTMLDivElement>(null);
  const wasLanding = useRef(landing);
  useEffect(() => {
    if (wasLanding.current && !landing)
      region.current?.focus({ preventScroll: true });
    wasLanding.current = landing;
  }, [landing]);

  if (landing) {
    const loads = Object.fromEntries(
      featured.map((id, index) => [id, loadOf(curricula[index]!)]),
    );
    const codeOf = (courseId: string) => {
      for (const [id, load] of Object.entries(loads)) {
        if (load.status !== 'ready') continue;
        const parsed = parseCurriculum(load.data, id);
        if (parsed.kind !== 'ok') continue;
        for (const group of parsed.data.semesters)
          for (const course of group.courses)
            if (course.course_id === courseId) return course.primary_code;
      }
      return null;
    };
    return (
      <SearchLanding
        programs={loadOf(programs)}
        curricula={loads}
        coop={loadOf(coop)}
        onOpenProgram={(id) =>
          void navigate(`/programs?program=${encodeURIComponent(id)}`)
        }
        onViewCourse={(courseId) =>
          openCourse(courseId, codeOf(courseId) ?? courseId)
        }
        onOpenCoop={() => void navigate('/coop')}
        onAsk={search.ask}
        onRetry={() => {
          if (programs.isError) void programs.refetch();
          for (const query of curricula)
            if (query.isError) void query.refetch();
          if (coop.isError) void coop.refetch();
        }}
      />
    );
  }
  const codeOf = (courseId: string) => {
    for (const turn of search.turns)
      if (turn.meta?.kind === 'ok') {
        const hit = turn.meta.results.find((r) => r.course_id === courseId);
        if (hit) return hit.primary_code;
      }
    return null;
  };
  return (
    <div
      ref={region}
      role="group"
      tabIndex={-1}
      className={styles.conversation}
      aria-label="对话"
    >
      <SearchConversation
        turns={search.turns}
        busy={search.busy}
        feedbackEnabled={search.feedback === true}
        onViewCourse={(courseId) =>
          openCourse(courseId, codeOf(courseId) ?? courseId)
        }
        onFollowUp={search.ask}
        onFeedback={sendFeedback}
      />
    </div>
  );
}

// The search column, and beside it a course when one is open (CourseRoute). On a phone a course page shows the course
// alone, as R1's layout does.
export function SearchWorkspace({ detail }: { detail?: ReactNode }) {
  const account = useAccount();
  return (
    <>
      {account.viewer?.kind === 'guest' && (
        <p className={styles.guest}>
          <Info aria-hidden="true" />
          <span>
            游客也能搜课、看培养方案。登录并分享一条 Co-op
            经验以后，能看到面试细节。<Link to="/coop">规则</Link>
          </span>
        </p>
      )}
      <div
        className={`${styles.columns} ${detail ? styles.detailOpen : styles.single}`}
      >
        <section className={styles.chat} aria-label="课程问答">
          <ProgramChoice />
          <SearchColumn />
        </section>
        {detail}
      </div>
    </>
  );
}

export function SearchRoute() {
  const [params] = useSearchParams();
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  // An old shared link, /?course=CS-5800, opens the course's page, in place of this address (R0 11). A return from
  // Google is useSession's; the link it came back to is handled after it.
  const ref = params.get('course')?.trim() ?? '';
  const login = isLoginReturn(pathname, search);
  useEffect(() => {
    if (ref !== '' && !login) void navigate(coursePath(ref), { replace: true });
  }, [ref, login, navigate]);
  return <SearchWorkspace />;
}
