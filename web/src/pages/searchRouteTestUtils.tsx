import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { QueryClient } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import type { MemoryRouterProps } from 'react-router-dom';
import { App } from '../App';
import type { DraftRequest } from '../api/draft';
import cs5800 from '../fixtures/course-detail/cs-5800-identity-only.json';
import cs6140 from '../fixtures/course-detail/cs-6140-everything.json';
import ds5220 from '../fixtures/course-detail/ds-5220-conflicts.json';
import alignEmpty from '../fixtures/draft/draft-align-empty.json';
import standardAdd from '../fixtures/draft/draft-standard-add.json';
import standardEmpty from '../fixtures/draft/draft-standard-empty.json';
import coop from '../fixtures/landing/coop-guest.json';
import aai from '../fixtures/landing/curriculum-aai-ms.json';
import ds from '../fixtures/landing/curriculum-ds-ms.json';
import programs from '../fixtures/landing/programs.json';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import cs from '../fixtures/programs/curriculum-cs-ms.json';
import cs7800 from '../fixtures/requisites/cs-7800-legacy-edges-only.json';
import alias from '../fixtures/search/alias-cs-6140.json';
import { apiError, fakeApi, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { WithApi, seededQueryClient } from '../test/withApi';

// The synthetic API the search and course pages ask in these tests (R3e): the landing's fixtures, cs-ms with its
// plans' content versions, one answer to every question, and the courses the fixtures have. A test answers what it
// needs to itself first.
export const CS = 'cs-ms';
export const ALIGN = 'cs-ms-boston-2026-2027-align';
export const STANDARD = 'cs-ms-boston-2026-2027-standard';
export const revisions: Readonly<Record<string, string>> =
  cs.proposed_plan_revisions;
export const csBody = (planRevisions: Record<string, string> = revisions) => ({
  ...cs.body,
  plan_revisions: planRevisions,
});
export const programRows = programs.body;
const curricula = new Map<string, unknown>([
  ['aai-ms', aai.body],
  [CS, csBody()],
  ['ds-ms', ds.body],
]);

// The landing's cs-ms starter, derived from the identity-only fixture.
const cs5010 = {
  ...cs5800.body,
  course_id: 'c-cs-5010',
  primary_code: 'CS 5010',
  primary_name: 'Programming Design Paradigm',
};
export const courses: readonly Record<string, unknown>[] = [
  cs6140.body,
  cs5800.body,
  ds5220.body,
  cs7800.body,
  cs5010,
];
export const identity = (body: Record<string, unknown>) => ({
  course_id: body.course_id as string,
  primary_code: body.primary_code as string,
  primary_name: body.primary_name as string,
});
// /resolve/course reads any separator; so does this.
const spelled = (code: string) => code.replace(/[^0-9a-z]/gi, '').toUpperCase();

// The draft check (R4c), from R4b's answers exported from the API: CS 5010 and CS 5800 added to the standard plan's
// empty draft is the export itself; anything else is the plan's empty draft with the courses asked for and those typed
// (only these two are known). The rule tree is the empty draft's: these tests read the courses, not the rules.
const draftCourses = standardAdd.body.courses;
export function draftAnswer(planId: string, request: DraftRequest) {
  const kept = draftCourses.filter((c) =>
    request.course_ids.includes(c.course_id),
  );
  const typed = new Set(request.input?.match(/[A-Z]{2,4} \d{4}/g) ?? []);
  const added = draftCourses.filter(
    (c) => typed.has(c.code) && !kept.includes(c),
  );
  const courses = [...kept, ...added];
  if (
    planId === STANDARD &&
    request.course_ids.length === 0 &&
    added.length === draftCourses.length
  )
    return {
      ...standardAdd.body,
      plan_content_sha256: request.plan_content_sha256,
    };
  return {
    ...structuredClone(planId === ALIGN ? alignEmpty.body : standardEmpty.body),
    plan_content_sha256: request.plan_content_sha256,
    courses,
    added: added.map((c) => c.code),
  };
}
const DRAFT_PATH = /^\/programs\/([^/]+)\/plans\/([^/]+)\/draft$/;
// The draft checks the page sent, in order: the plan and the body.
export const draftChecks = (calls: readonly Call[]) =>
  calls.flatMap((call) => {
    const path = DRAFT_PATH.exec(call.path);
    return call.method === 'POST' && path
      ? [{ plan: decodeURIComponent(path[2]!), body: call.body }]
      : [];
  });

export const stream = (lines: readonly unknown[]) =>
  new Response(lines.map((line) => JSON.stringify(line)).join('\n') + '\n');
export const answerText = (lines: readonly { type: string; text?: string }[]) =>
  lines
    .filter((line) => line.type === 'token')
    .map((line) => line.text)
    .join('');

function standard(call: Call): Response {
  const asked = `${call.method} ${call.path}`;
  if (asked === 'GET /programs') return json(programRows);
  const draft = DRAFT_PATH.exec(call.path);
  if (call.method === 'POST' && draft)
    return json(
      draftAnswer(decodeURIComponent(draft[2]!), call.body as DraftRequest),
    );
  if (call.method === 'GET' && call.path.startsWith('/programs/')) {
    const body = curricula.get(
      decodeURIComponent(call.path.slice('/programs/'.length)),
    );
    return body === undefined
      ? apiError(404, 'not_found', 'Program not found')
      : json(body);
  }
  if (asked === 'GET /coop') return json(coop.body);
  if (asked === 'GET /privacy') return json(privacy.body);
  if (asked === 'POST /chat') return stream(alias.lines);
  if (asked === 'POST /feedback') {
    const vote = call.body as { answer_id: string; rating: string };
    return json({ answer_id: vote.answer_id, rating: vote.rating });
  }
  if (asked === 'GET /resolve/course') {
    const ref = new URLSearchParams(call.search).get('ref') ?? '';
    return json({
      ref,
      matches: courses
        .filter((body) => spelled(body.primary_code as string) === spelled(ref))
        .map(identity),
    });
  }
  if (call.method === 'GET' && call.path.startsWith('/course/')) {
    const id = decodeURIComponent(call.path.slice('/course/'.length));
    const body = courses.find((course) => course.course_id === id);
    return body === undefined
      ? apiError(404, 'not_found', 'Course not found')
      : json(body);
  }
  return apiError(404, 'not_found', 'Not found');
}

export function world(
  own: (call: Call) => Response | Promise<Response> | undefined = () =>
    undefined,
) {
  return fakeApi((call) => own(call) ?? standard(call));
}

// Where the page is, with the state a link handed along, and Back and Forward buttons.
function Where() {
  const { pathname, search, state } = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="where" data-state={JSON.stringify(state ?? null)}>
        {`${pathname}${search}`}
      </output>
      <button type="button" onClick={() => void navigate(-1)}>
        back
      </button>
      <button type="button" onClick={() => void navigate(1)}>
        forward
      </button>
    </>
  );
}
type Entry = NonNullable<MemoryRouterProps['initialEntries']>[number];
// The whole app at one of these addresses (the last, unless `at` says which), the others around it in the history.
export function page(
  entries: Entry | readonly Entry[],
  client: QueryClient = seededQueryClient(),
  at?: number,
) {
  const list = Array.isArray(entries) ? [...entries] : [entries as Entry];
  const view = render(
    <WithApi client={client}>
      <MemoryRouter initialEntries={list} initialIndex={at ?? list.length - 1}>
        <App />
        <Where />
      </MemoryRouter>
    </WithApi>,
  );
  return { client, ...view };
}
const whereNode = () => screen.getByRole('status', { name: 'where' });
export const where = () => whereNode().textContent;
export const stateOf = () =>
  JSON.parse(whereNode().dataset.state ?? 'null') as unknown;

export async function choose(label: string, option: string) {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole('combobox', { name: (name) => name.startsWith(label) }),
  );
  await user.click(screen.getByRole('option', { name: option }));
}
export const combobox = (label: string) =>
  screen.queryByRole('combobox', { name: (name) => name.startsWith(label) });
export const chats = (calls: readonly Call[]) =>
  calls.filter((call) => call.path === '/chat').map((call) => call.body);
