import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { App } from '../App';
import ready from '../fixtures/programs/policies-cs-ms-standard-ready.json';
import { PLAN_LINK_NOTICES } from '../models/programLinks';
import { CHECKING_LINK } from '../pages/ProgramsRoute';
import {
  CS,
  STANDARD,
  combobox,
  csBody,
  revisions,
  world,
} from '../pages/searchRouteTestUtils';
import { held, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { WithApi, seededQueryClient } from '../test/withApi';

// The shell's skip link under the router the site runs under (BrowserRouter), on jsdom's own history: an in-page link
// there is a history entry of its own, with no state, and the router follows it (R4c recheck A33 R2-1, R6).
const PLAN = '选择目录版本与路径';
const STANDARD_PLAN =
  'boston · Catalog 2026-2027 · 普通 MS · 共同部分／未限定 concentration';
const CURRICULUM = `/programs/${CS}`;
const POLICIES = `/programs/${CS}/plans/${STANDARD}/policies`;
const policies = (call: Call) =>
  call.path === POLICIES ? json(ready.body) : undefined;
const linkNotice = () => screen.getByRole('status', { name: '分享链接' });
const planLink = () =>
  '/?' +
  new URLSearchParams({
    plan_v: '1',
    program: CS,
    plan: STANDARD,
    campus: 'boston',
    catalog_year: '2026-2027',
    pathway: 'standard',
    concentration: 'null',
    plan_revision: revisions[STANDARD]!,
  }).toString();

function browserPage(address: string) {
  window.history.replaceState(null, '', address);
  render(
    <WithApi client={seededQueryClient()}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </WithApi>,
  );
}
const skip = () =>
  userEvent.click(screen.getByRole('link', { name: '跳到主要内容' }));

it('the skip link moves focus to the main content and leaves the address and the history as they are', async () => {
  world();
  browserPage('/compare');
  await screen.findAllByRole('heading', { name: '课程对比' });
  screen.getByRole('link', { name: '跳到主要内容' }).focus();
  const length = window.history.length;
  const state: unknown = window.history.state;
  await skip();
  expect(screen.getByRole('main')).toHaveFocus();
  expect(window.location.pathname + window.location.hash).toBe('/compare');
  expect(window.history.length).toBe(length);
  expect(window.history.state).toEqual(state);
});

it('pressed while a plan link is checked, the shared plan is chosen all the same', async () => {
  const later = held();
  let reads = 0;
  world((call) =>
    call.method === 'GET' && call.path === CURRICULUM && ++reads === 1
      ? later.response
      : policies(call),
  );
  browserPage(planLink());
  await waitFor(() => expect(linkNotice()).toHaveTextContent(CHECKING_LINK));
  await skip();
  expect(linkNotice()).toHaveTextContent(CHECKING_LINK);
  later.answer(json(csBody()));
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
  );
  expect(window.location.pathname + window.location.hash).toBe(CURRICULUM);
  expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
  expect(reads).toBe(1);
});
