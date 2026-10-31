import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { GUEST } from '../api/queries';
import type { Viewer } from '../api/queries';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import { fakeApi, json } from '../test/fakeApi';
import { WithApi, seededQueryClient } from '../test/withApi';
import { AccountContext } from './account';
import type { Account } from './account';
import {
  AskBar,
  CAPTURE_LABEL,
  CAPTURE_OFF,
  PLACEHOLDER,
  QUERY_LOG_FALLBACK,
} from './AskBar';
import { SearchContext } from './SearchContext';
import type { SearchState } from './SearchContext';

const NOTICE = '合成的查询日志说明：提问原文会记进不公开的日志。';
const CAPTURE = '合成的保存说明：勾选后，之后正常完成的回答会不公开地保存。';

function account(viewer: Viewer | undefined): Account {
  return {
    viewer,
    unsure: false,
    login: vi.fn(),
    signedOut: vi.fn(async () => {}),
    contributed: vi.fn(async () => {}),
  };
}
// A search state of the test's own; the opt-in really toggles.
function Search({
  state,
  children,
}: {
  state: SearchState;
  children: ReactNode;
}) {
  const [allowSave, setAllowSave] = useState(false);
  return (
    <SearchContext.Provider value={{ ...state, allowSave, setAllowSave }}>
      {children}
    </SearchContext.Provider>
  );
}
function setup({
  feedback = true as boolean | null,
  busy = false,
  // false: /auth/me has not said yet who is looking.
  known = true,
  body = {
    ...privacy.body,
    query_log_notice: NOTICE,
    capture_notice: CAPTURE,
  } as Record<string, unknown>,
} = {}) {
  const api = fakeApi(async ({ path }) =>
    path === '/privacy' ? json(body) : json({}, 404),
  );
  const send = vi.fn();
  const state: SearchState = {
    turns: [],
    busy,
    ask: vi.fn(),
    programId: null,
    chooseProgram: vi.fn(),
    plans: [],
    plan: null,
    choosePlan: vi.fn(),
    planRevised: false,
    plansUnavailable: false,
    allowSave: false,
    setAllowSave: vi.fn(),
    feedback,
  };
  render(
    <WithApi client={seededQueryClient()}>
      <MemoryRouter>
        <AccountContext.Provider value={account(known ? GUEST : undefined)}>
          <Search state={state}>
            <AskBar onSend={send} />
          </Search>
        </AccountContext.Provider>
      </MemoryRouter>
    </WithApi>,
  );
  return {
    api,
    send,
    user: userEvent.setup(),
    input: screen.getByRole('textbox', { name: '课程问题' }),
    button: screen.getByRole('button', { name: '发送问题' }),
  };
}

it('says the query log notice before every question: the API’s words, and its sentence until they come', async () => {
  const { api, input } = setup();
  expect(screen.getByText(QUERY_LOG_FALLBACK, { exact: false })).toBeVisible();
  expect(await screen.findByText(NOTICE, { exact: false })).toBeVisible();
  expect(
    screen.queryByText(QUERY_LOG_FALLBACK, { exact: false }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '数据与隐私' })).toHaveAttribute(
    'href',
    '/privacy',
  );
  expect(input.getAttribute('aria-describedby')).toMatch(/privacy$/);
  expect(input).toHaveAttribute('placeholder', PLACEHOLDER);
  expect(api.count('GET', '/privacy')).toBe(1);
});

it('asks nothing before it is known who is looking (R2b: back from Google, only the login goes out)', async () => {
  const { api } = setup({ known: false });
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(api.calls.map(({ method, path }) => `${method} ${path}`)).toEqual([]);
  expect(screen.getByText(QUERY_LOG_FALLBACK, { exact: false })).toBeVisible();
});

// What is held at the bottom of the window is the form: the query log's sentence and the question. The opt-in and its
// notice are under it, in the page; held with it, they made it half a phone's window (review A34).
function underTheBox(element: HTMLElement) {
  const form = screen.getByRole('form', { name: '提问' });
  expect(form).toContainElement(screen.getByText(NOTICE, { exact: false }));
  expect(form).not.toContainElement(element);
  expect(
    form.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
}

it('with answer feedback on: the opt-in and the API’s notice', async () => {
  const { user, send, input, button } = setup();
  const box = await screen.findByRole('checkbox', { name: CAPTURE_LABEL });
  expect(box).not.toBeChecked();
  expect(screen.getByText(CAPTURE)).toBeVisible();
  underTheBox(box);
  underTheBox(screen.getByText(CAPTURE));
  await user.click(box);
  expect(box).toBeChecked();
  await user.type(input, 'CS 6140');
  await user.click(button);
  expect(send).toHaveBeenCalledExactlyOnceWith('CS 6140');
  // That it stays ticked after a question is the search state's to keep: SearchRoute.test asks it on the whole page.
});

it('with answer feedback off: no opt-in, and Streamlit’s line that nothing is saved', async () => {
  setup({ feedback: false });
  expect(await screen.findByText(NOTICE, { exact: false })).toBeVisible();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.getByText(CAPTURE_OFF)).toBeVisible();
  underTheBox(screen.getByText(CAPTURE_OFF));
});

it('says nothing of saving while /config has not answered', async () => {
  setup({ feedback: null });
  expect(await screen.findByText(NOTICE, { exact: false })).toBeVisible();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByText(CAPTURE_OFF)).not.toBeInTheDocument();
});

it('offers no opt-in the API gave no notice for', async () => {
  setup({
    body: { ...privacy.body, query_log_notice: NOTICE, capture_notice: null },
  });
  expect(await screen.findByText(NOTICE, { exact: false })).toBeVisible();
  await waitFor(() =>
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(),
  );
});

it('disables sending empty or whitespace text', async () => {
  const { user, send, input, button } = setup();
  expect(button).toBeDisabled();
  await user.type(input, '   ');
  expect(button).toBeDisabled();
  await user.keyboard('{Enter}');
  expect(send).not.toHaveBeenCalled();
});

it('Enter sends trimmed input and clears the field', async () => {
  const { user, send, input, button } = setup();
  await user.type(input, '  CS 5800  ');
  expect(button).toBeEnabled();
  await user.keyboard('{Enter}');
  expect(send).toHaveBeenCalledExactlyOnceWith('CS 5800');
  expect(input).toHaveValue('');
  expect(button).toBeDisabled();
});

it('Shift+Enter inserts a newline without sending', async () => {
  const { user, send, input } = setup();
  await user.type(input, '第一行');
  await user.keyboard('{Shift>}{Enter}{/Shift}');
  await user.type(input, '第二行');
  expect(input).toHaveValue('第一行\n第二行');
  expect(send).not.toHaveBeenCalled();
});

it('does not send while the input method is composing', async () => {
  const { user, send, input } = setup();
  await user.type(input, '算法');
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
  expect(send).not.toHaveBeenCalled();
});

it('takes 500 characters, counted as the API counts them, and says so past that', async () => {
  const { send, input, button } = setup();
  // A character outside the BMP is two UTF-16 units and one character.
  fireEvent.change(input, { target: { value: '𝟙'.repeat(500) } });
  expect(button).toBeEnabled();
  expect(input).toHaveAttribute('aria-invalid', 'false');
  fireEvent.change(input, { target: { value: ` ${'字'.repeat(501)} ` } });
  expect(button).toBeDisabled();
  const limit = screen.getByText(
    '问题最多 500 个字，现在是 501 个字；改短一点再发。',
  );
  expect(input).toHaveAttribute('aria-invalid', 'true');
  expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(
    limit.id,
  );
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(send).not.toHaveBeenCalled();
});

it('sends nothing while the last answer is on its way', async () => {
  const { user, send, input, button } = setup({ busy: true });
  await user.type(input, 'CS 5800');
  expect(button).toBeDisabled();
  await user.keyboard('{Enter}');
  expect(send).not.toHaveBeenCalled();
  expect(input).toHaveValue('CS 5800');
});
