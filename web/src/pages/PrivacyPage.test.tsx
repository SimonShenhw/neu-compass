import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode, useState } from 'react';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { DeleteOutcome, PrivacyPageProps } from '../api/privacy';
import p90 from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import pOff from '../fixtures/privacy/privacy-no-cleanup-feedback-off.json';
import p30 from '../fixtures/privacy/privacy-30-days-feedback-no-contact.json';
import pContact from '../fixtures/privacy/privacy-no-cleanup-feedback-contact.json';
import ok from '../fixtures/privacy/delete-ok.json';
import okEmpty from '../fixtures/privacy/delete-ok-nothing-else.json';
import stale from '../fixtures/privacy/delete-401-cookie-not-valid.json';
import gone from '../fixtures/privacy/delete-401-account-gone.json';
import crossSite from '../fixtures/privacy/delete-403-cross-site.json';
import wrongWord from '../fixtures/privacy/delete-422-wrong-word.json';
import { PrivacyPage } from './PrivacyPage';

const success =
  '你的账号和 Co-op 投稿已经删除，本页已登出。每日备份里的副本最多再留大约两周。';
const expired =
  '这个登录已经失效，本页已登出。如果账号还在，请重新登录以后再删除。';
const uncertain =
  '这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。';
const refused =
  '删除没有完成，什么也没删。请稍后再试；一直不行的话，请写邮件联系。';
const checkbox = () =>
  screen.getByRole('checkbox', { name: '我知道删除以后不能恢复' });
const deleteButton = () =>
  screen.getByRole('button', { name: '删除我的账号和投稿' });
function props(overrides: Partial<PrivacyPageProps> = {}): PrivacyPageProps {
  return {
    viewer: { kind: 'member' },
    privacy: { status: 'ready', body: p90.body },
    onRetry: vi.fn(),
    onDelete: vi.fn(async (): Promise<DeleteOutcome> => ({
      ok: false,
      status: 503,
    })),
    onSignedOut: vi.fn(),
    ...overrides,
  };
}
function deferred() {
  let resolve!: (value: DeleteOutcome) => void;
  const promise = new Promise<DeleteOutcome>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
for (const fixture of [p90, pOff, p30, pContact]) {
  it(`renders exact API prose and order without notice leakage: ${fixture.case}`, () => {
    const { container } = render(
      <PrivacyPage
        {...props({ privacy: { status: 'ready', body: fixture.body } })}
      />,
    );
    expect(
      screen.getByText(fixture.body.intro, { exact: true }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole('heading', { level: 2 }).map((e) => e.textContent),
    ).toEqual([
      ...fixture.body.sections.map((s) => s.heading),
      '删除我的账号和投稿',
    ]);
    expect(
      screen.getAllByRole('list').map((e) =>
        within(e)
          .getAllByRole('listitem')
          .map((li) => li.textContent),
      ),
    ).toEqual(fixture.body.sections.map((s) => s.sentences));
    expect(
      screen.getByText(fixture.body.delete_what, { exact: true }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll('a')).toHaveLength(0);
    expect(
      screen.queryByText(fixture.body.query_log_notice, { exact: true }),
    ).not.toBeInTheDocument();
    if (fixture.body.capture_notice)
      expect(
        screen.queryByText(fixture.body.capture_notice, { exact: true }),
      ).not.toBeInTheDocument();
    expect(deleteButton()).toBeDisabled();
    expect(checkbox()).not.toBeChecked();
  });
  it(`guest never has deletion or extra login controls: ${fixture.case}`, () => {
    render(
      <PrivacyPage
        {...props({
          viewer: { kind: 'guest' },
          privacy: { status: 'ready', body: fixture.body },
        })}
      />,
    );
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(4);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
}
it('member confirmation is required even for a synthetic form submission', async () => {
  const onDelete = vi.fn(async (): Promise<DeleteOutcome> => ({
    ok: false,
    status: 403,
  }));
  render(<PrivacyPage {...props({ onDelete })} />);
  fireEvent.submit(screen.getByRole('form', { name: '删除我的账号和投稿' }));
  expect(onDelete).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(checkbox());
  expect(deleteButton()).toBeEnabled();
  await user.click(deleteButton());
  expect(onDelete).toHaveBeenCalledExactlyOnceWith();
});
it.each([
  null,
  [],
  { intro: 'x' },
  { ...p90.body, sections: [] },
  { ...p90.body, sections: [{ heading: 'x', sentences: [2] }] },
  { ...p90.body, delete_what: 7 },
  { ...p90.body, intro: 7 },
  { ...p90.body, sections: 'wrong' },
  { ...p90.body, sections: [{ heading: 7, sentences: [] }] },
  { ...p90.body, sections: [{ heading: 'x', sentences: 'wrong' }] },
  { ...p90.body, sections: [null] },
])('invalid privacy body %j fails closed as a whole', (body) => {
  render(<PrivacyPage {...props({ privacy: { status: 'ready', body } })} />);
  expect(
    screen.getByText('隐私说明暂时加载不了，请稍后重试。'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByText(p90.body.intro)).not.toBeInTheDocument();
});
it.each([503, null])(
  'privacy error %s exposes only retry with no event argument',
  async (httpStatus) => {
    const p = props({ privacy: { status: 'error', httpStatus } });
    render(<PrivacyPage {...p} />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '重试' }));
    expect(p.onRetry).toHaveBeenCalledExactlyOnceWith();
  },
);
it('loading has only a loading status, no prose or deletion', () => {
  render(<PrivacyPage {...props({ privacy: { status: 'loading' } })} />);
  expect(screen.getByRole('status')).toHaveTextContent('正在加载');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
});
const outcomes: [string, DeleteOutcome, string, boolean][] = [
  [ok.case, { ok: true, result: { ...ok.body, deleted: true } }, success, true],
  [
    okEmpty.case,
    { ok: true, result: { ...okEmpty.body, deleted: true } },
    success,
    true,
  ],
  [stale.case, { ok: false, status: stale.status }, expired, true],
  [gone.case, { ok: false, status: gone.status }, expired, true],
  [crossSite.case, { ok: false, status: crossSite.status }, refused, false],
  [wrongWord.case, { ok: false, status: wrongWord.status }, refused, false],
  ...[429, 500].map(
    (status) =>
      [String(status), { ok: false, status }, refused, false] as [
        string,
        DeleteOutcome,
        string,
        boolean,
      ],
  ),
  ...[null, 502, 503, 504].map(
    (status) =>
      [String(status), { ok: false, status }, uncertain, false] as [
        string,
        DeleteOutcome,
        string,
        boolean,
      ],
  ),
];
it.each(outcomes)(
  'deletion outcome %s preserves exact result and focus across signout',
  async (_name, outcome, text, signsOut) => {
    const onSignedOut = vi.fn();
    function Host() {
      const [kind, setKind] = useState<'member' | 'guest'>('member');
      return (
        <PrivacyPage
          {...props({
            viewer: { kind },
            onDelete: async () => outcome,
            onSignedOut: () => {
              onSignedOut();
              setKind('guest');
            },
          })}
        />
      );
    }
    const { container } = render(
      <StrictMode>
        <Host />
      </StrictMode>,
    );
    const user = userEvent.setup();
    await user.click(checkbox());
    await user.click(deleteButton());
    const notice = screen.getByRole('status', { name: '删除结果' });
    expect(notice).toHaveTextContent(text);
    expect(notice).toHaveFocus();
    expect(notice).toHaveAttribute('tabindex', '-1');
    expect(onSignedOut).toHaveBeenCalledTimes(signsOut ? 1 : 0);
    expect(screen.queryByRole('checkbox') !== null).toBe(!signsOut);
    const rendered = container.textContent!;
    expect(rendered.indexOf(p90.body.intro)).toBeLessThan(
      rendered.indexOf(text),
    );
    expect(rendered.indexOf(text)).toBeLessThan(
      rendered.indexOf(p90.body.sections[0]!.heading),
    );
    expect(rendered).not.toMatch(
      /Unknown user\.|Cross-site request refused\.|Input should be|published_experiences|withdrawn_from_groups/,
    );
    if (text === uncertain) expect(rendered).not.toContain('就是已经删掉了');
  },
);
it('thrown deletion remains uncertain and never signs out', async () => {
  const p = props({
    onDelete: async () => {
      throw Error('PRIVATE error detail');
    },
  });
  const { container } = render(<PrivacyPage {...p} />);
  const user = userEvent.setup();
  await user.click(checkbox());
  await user.click(deleteButton());
  expect(screen.getByRole('status', { name: '删除结果' })).toHaveTextContent(
    uncertain,
  );
  expect(p.onSignedOut).not.toHaveBeenCalled();
  expect(container).not.toHaveTextContent('PRIVATE error detail');
});
it('in-flight guard disables both controls, rejects double submit and clears old result before retry', async () => {
  const first = deferred(),
    second = deferred();
  const onDelete = vi
    .fn()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  render(<PrivacyPage {...props({ onDelete })} />);
  fireEvent.click(checkbox());
  const form = screen.getByRole('form', { name: '删除我的账号和投稿' });
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(onDelete).toHaveBeenCalledTimes(1);
  expect(checkbox()).toBeDisabled();
  expect(screen.getByRole('button', { name: '正在删除…' })).toBeDisabled();
  await act(async () => first.resolve({ ok: false, status: 403 }));
  expect(screen.getByRole('status', { name: '删除结果' })).toHaveFocus();
  fireEvent.submit(form);
  expect(
    screen.queryByRole('status', { name: '删除结果' }),
  ).not.toBeInTheDocument();
  await act(async () => second.resolve({ ok: false, status: 403 }));
  expect(screen.getByRole('status', { name: '删除结果' })).toHaveFocus();
});
it.each(['unmount', 'guest', 'invalid-policy', 'relogin'])(
  'late deletion after %s cannot change state or sign out',
  async (mode) => {
    const task = deferred();
    const p = props({ onDelete: () => task.promise });
    const view = render(<PrivacyPage {...p} />);
    fireEvent.click(checkbox());
    fireEvent.click(deleteButton());
    if (mode === 'unmount') view.unmount();
    else
      view.rerender(
        <PrivacyPage
          {...p}
          {...(mode === 'guest' || mode === 'relogin'
            ? { viewer: { kind: 'guest' as const } }
            : { privacy: { status: 'ready' as const, body: null } })}
        />,
      );
    if (mode === 'relogin') view.rerender(<PrivacyPage {...p} />);
    await act(async () =>
      task.resolve({ ok: true, result: { ...ok.body, deleted: true } }),
    );
    expect(p.onSignedOut).not.toHaveBeenCalled();
    expect(
      screen.queryByRole('status', { name: '删除结果' }),
    ).not.toBeInTheDocument();
  },
);
it('relogin resets confirmation and preserves the previous result without stealing focus', async () => {
  const p = props({ onDelete: async () => ({ ok: false, status: 403 }) });
  const view = render(<PrivacyPage {...p} />);
  const user = userEvent.setup();
  await user.click(checkbox());
  await user.click(deleteButton());
  const notice = screen.getByRole('status', { name: '删除结果' });
  view.rerender(<PrivacyPage {...p} viewer={{ kind: 'guest' }} />);
  expect(notice).toHaveFocus();
  view.rerender(<PrivacyPage {...p} />);
  expect(checkbox()).not.toBeChecked();
  expect(deleteButton()).toBeDisabled();
  expect(notice).toHaveFocus();
});
it('API-controlled text remains literal including headings, intro, delete explanation and list items', () => {
  const text = '<b>x</b> [链接](https://example.com) privacy@example.test';
  const body = {
    ...p90.body,
    intro: text,
    delete_what: text,
    sections: [{ heading: text, sentences: [text] }],
  };
  const { container } = render(
    <PrivacyPage {...props({ privacy: { status: 'ready', body } })} />,
  );
  expect(screen.getAllByText(text, { exact: true })).toHaveLength(4);
  expect(container.querySelectorAll('b,a')).toHaveLength(0);
});
it('unused API keys are ignored instead of making extra prose or links', () => {
  render(
    <PrivacyPage
      {...props({
        privacy: {
          status: 'ready',
          body: {
            intro: 'API intro',
            delete_what: 'API deletion',
            sections: [{ heading: 'Future heading', sentences: [] }],
            query_log_notice: 123,
            capture_notice: { bad: true },
            extra: 'hidden',
          },
        },
      })}
    />,
  );
  expect(
    screen.getByRole('heading', { name: 'Future heading' }),
  ).toBeInTheDocument();
  expect(screen.getByText('API deletion')).toBeInTheDocument();
  expect(screen.queryByText('hidden')).not.toBeInTheDocument();
});
it('privacy interactions never write browser storage or console output', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  const log = vi.spyOn(console, 'log'),
    info = vi.spyOn(console, 'info'),
    warn = vi.spyOn(console, 'warn'),
    error = vi.spyOn(console, 'error');
  try {
    render(<PrivacyPage {...props()} />);
    const user = userEvent.setup();
    await user.click(checkbox());
    await user.click(deleteButton());
    for (const spy of [storage, log, info, warn, error])
      expect(spy).not.toHaveBeenCalled();
  } finally {
    for (const spy of [storage, log, info, warn, error]) spy.mockRestore();
  }
});
it.each(['guest', 'member', 'error', 'result'])(
  'axe privacy %s has no violations',
  async (mode) => {
    const { container } = render(
      <PrivacyPage
        {...props({
          viewer: { kind: mode === 'guest' ? 'guest' : 'member' },
          privacy:
            mode === 'error'
              ? { status: 'error', httpStatus: 503 }
              : { status: 'ready', body: p90.body },
        })}
      />,
    );
    if (mode === 'result') {
      fireEvent.click(checkbox());
      await act(async () => fireEvent.click(deleteButton()));
    }
    expect(
      (
        await axe(container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  },
);
