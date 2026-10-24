import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { SearchConversation } from './SearchConversation';
import { fixtureTurn, expandSearch } from './searchTestUtils';
import { newTurn, turnReducer } from '../../models/chatTurn';
import { parseChatMeta } from '../../models/chatMeta';
import { searchFixture } from '../../fixtures/searchDemo';
import type { FeedbackVote } from '../../api/chat';

const props = () => ({
  busy: false,
  feedbackEnabled: false,
  onViewCourse: vi.fn(),
  onFollowUp: vi.fn(),
  onFeedback: vi
    .fn<(vote: FeedbackVote) => Promise<unknown>>()
    .mockResolvedValue(null),
});
it('feedback immediately rejects changed receipt fields even when the parent reuses the same object', async () => {
  const t = fixtureTurn('feedback-receipt').turn,
    p = props();
  const { rerender } = render(
    <SearchConversation {...p} turns={[t]} feedbackEnabled />,
  );
  await screen.findByRole('button', { name: '有帮助' });
  (t.receipt as Record<string, unknown>).feedback_token = 'x'.repeat(42);
  rerender(<SearchConversation {...p} turns={[t]} feedbackEnabled />);
  expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
});
it('plan placement labels use the last course record for duplicate IDs like the Python mapping', async () => {
  const t = fixtureTurn('plan-ds-align').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  t.meta.results.push({ ...t.meta.results[0]!, primary_code: 'LATEST CODE' });
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  await expandSearch(container);
  const plan = [...container.querySelectorAll('details')].find(
    (d) => d.querySelector('summary')?.textContent === '所选方案与课程位置',
  )!;
  expect(within(plan).getAllByText(/^LATEST CODE：/).length).toBeGreaterThan(0);
});
it('waiting and pre-token answering show loading and announce state, never token text', () => {
  const turn = newTurn(1, '<b>q</b>\nline', false),
    p = props();
  const { rerender } = render(
    <SearchConversation {...p} turns={[turn]} busy />,
  );
  expect(screen.getByText('正在查找相关的课…')).toBeVisible();
  expect(screen.getByRole('article')).toHaveAttribute('aria-busy', 'true');
  expect(screen.getByRole('status', { name: '回答状态' })).toHaveTextContent(
    '正在回答…',
  );
  const meta = searchFixture('alias-cs-6140').events[0]!;
  const answering = turnReducer(turn, meta);
  rerender(<SearchConversation {...p} turns={[answering]} busy />);
  expect(screen.getByText('正在生成回答…')).toBeVisible();
  expect(screen.getByText('相关课程（1 门）')).toBeVisible();
  rerender(
    <SearchConversation
      {...p}
      turns={[turnReducer(answering, { type: 'token', text: 'partial' })]}
      busy
    />,
  );
  expect(screen.getByText('partial')).toBeVisible();
  expect(screen.queryByText('正在生成回答…')).toBeNull();
  expect(
    screen.getByRole('status', { name: '回答状态' }),
  ).not.toHaveTextContent('partial');
});
it('related disclosure defaults by count, respects user collapse across streaming rerenders and callbacks use IDs', async () => {
  const t = fixtureTurn('alias-cs-6140').turn,
    p = props();
  const { container, rerender } = render(
    <SearchConversation {...p} turns={[{ ...t, status: 'answering' }]} busy />,
  );
  const details = container.querySelector('details')!;
  expect(details.open).toBe(true);
  const user = userEvent.setup();
  await user.click(details.querySelector('summary')!);
  expect(details.open).toBe(false);
  rerender(
    <SearchConversation {...p} turns={[{ ...t, text: t.text + ' next' }]} />,
  );
  expect(details.open).toBe(false);
  await user.click(details.querySelector('summary')!);
  await user.click(screen.getByRole('button', { name: '查看 CS 6140' }));
  expect(p.onViewCourse).toHaveBeenCalledExactlyOnceWith('c-cs-6140');
  expect(screen.queryByRole('button', { name: '加入对比' })).toBeNull();
  rerender(
    <SearchConversation
      {...p}
      turns={[{ ...fixtureTurn('hybrid-neural-network').turn, id: 2 }]}
    />,
  );
  expect(container.querySelector('details')!.open).toBe(false);
});
it('followups only occur on the last eligible ended turn, and busy blocks callbacks', async () => {
  const a = fixtureTurn('alias-cs-6140').turn,
    b = { ...a, id: 2 },
    p = props();
  const { rerender } = render(
    <SearchConversation {...p} turns={[a, b]} busy />,
  );
  const group = screen.getByRole('group', { name: '接着问' });
  expect(screen.getAllByRole('group', { name: '接着问' })).toHaveLength(1);
  for (const button of within(group).getAllByRole('button')) {
    expect(button).toBeDisabled();
    await userEvent.setup().click(button);
  }
  expect(p.onFollowUp).not.toHaveBeenCalled();
  rerender(<SearchConversation {...p} turns={[a, b]} />);
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '先修要求是什么？' }));
  expect(p.onFollowUp).toHaveBeenCalledExactlyOnceWith('先修要求是什么？');
  if (b.meta?.kind !== 'ok') throw Error('fixture');
  for (const matched_via of ['rejected', 'empty']) {
    rerender(
      <SearchConversation
        {...p}
        turns={[{ ...b, meta: { ...b.meta, matched_via } }]}
      />,
    );
    expect(screen.queryByRole('group', { name: '接着问' })).toBeNull();
  }
});
it('invalid results hide the full course block, plan and followups without removing the answer', () => {
  const t = fixtureTurn('plan-ds-align').turn;
  render(
    <SearchConversation
      {...props()}
      turns={[
        {
          ...t,
          text: 'kept',
          meta: parseChatMeta({
            matched_via: 'hybrid',
            results: [{ course_id: 'x' }],
          }),
        },
      ]}
    />,
  );
  expect(screen.getByText('kept')).toBeVisible();
  expect(screen.getByText('相关课程的格式不对，没有显示。')).toBeVisible();
  expect(screen.queryByText('所选方案与课程位置')).toBeNull();
  expect(screen.queryByRole('group', { name: '接着问' })).toBeNull();
});
it('untrusted questions, course labels, plan paths, areas, conditions and noncatalog answer URLs stay literal', async () => {
  const t = fixtureTurn('plan-ds-align').turn,
    text = '<b>x</b> [链接](https://example.com) javascript:alert(1)';
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  t.question = text;
  t.text = text;
  for (const result of t.meta.results) result.primary_name = text;
  const plan = t.meta.plan_context as {
    placements: Record<
      string,
      { path: string[]; areas: string[]; activate_when: string[] }[]
    >;
  };
  for (const entries of Object.values(plan.placements))
    for (const entry of entries) {
      entry.path = [text];
      entry.areas = [text];
      entry.activate_when = [text];
    }
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  await expandSearch(container);
  expect(screen.getAllByText(text).length).toBeGreaterThan(2);
  expect(container.querySelector('b,img,script')).toBeNull();
  expect(container.querySelectorAll('a')).toHaveLength(1);
  expect(container.querySelector('a')).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  );
  expect(container.textContent).toContain('条件：' + text);
  expect(container.textContent).toContain('所属领域：' + text);
});
it('compact evidence excludes noncompact notices, caps missing labels at five and keeps other lines after invalid requisite data', async () => {
  const t = fixtureTurn('alias-cs-6140').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  const r = t.meta.results[0]!;
  if (!r.evidence) throw Error('fixture');
  r.evidence.warnings = [
    'topics_source_unavailable',
    'catalog_source_unavailable',
    'program_seed_unverified',
  ];
  r.evidence.missing_fields = [
    'credits',
    'term',
    'delivery_mode',
    'professor',
    'prereqs',
    'unknown',
  ];
  r.requisites = { storage: 'invalid' };
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  await expandSearch(container);
  expect(screen.getByText('来源：已存目录快照（非实时核验）')).toBeVisible();
  expect(
    screen.getByText(
      '缺失：学分、开课学期、授课方式、教师、结构化先修信息等 6 项（详情查看全部）；缺失不等于零/简单/无要求。',
    ),
  ).toBeVisible();
  expect(
    screen.getByText('培养方案关系没有核实，不是正式的 Plan of Study。'),
  ).toBeVisible();
  expect(container.textContent).not.toContain('主题列表没有来源');
  expect(container.textContent).not.toContain('没有官方目录的存档');
});
it('compact evidence calls a snapshot that failed its check untraceable', async () => {
  const t = fixtureTurn('alias-cs-6140').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  const e = t.meta.results[0]!.evidence;
  if (!e) throw Error('fixture');
  e.catalog = { kind: 'invalid' };
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  await expandSearch(container);
  expect(screen.getByText('来源：未附可追溯目录快照')).toBeVisible();
  expect(container.textContent).not.toContain('已存目录快照');
});
it('result cards show 没有结果 for an unknown route and fold the course code onto one line', () => {
  const t = fixtureTurn('alias-cs-6140').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  t.meta.matched_via = 'new-route';
  t.meta.results[0]!.primary_code = 'CS\f6140\n';
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  expect(container.querySelector('[data-kind="badge"]')!.textContent).toBe(
    '没有结果',
  );
  expect(container.querySelector('[data-code]')!.textContent).toBe('CS 6140');
  expect(screen.getByRole('button', { name: '查看 CS 6140' })).toBeVisible();
});
it('score bars are measured against the highest score even when it is not listed first', () => {
  const t = fixtureTurn('hybrid-neural-network').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  const [first, second] = t.meta.results;
  t.meta.results = [
    { ...first!, score: 0.5 },
    { ...second!, score: 1 },
  ];
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  expect(
    [...container.querySelectorAll<HTMLElement>('[data-score-bar]')].map(
      (bar) => bar.style.width,
    ),
  ).toEqual(['50%', '100%']);
});
it('plan position says when the plan does not place a course and when places were left out, and its source opens in a new tab', async () => {
  const t = fixtureTurn('plan-ds-align').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  const plan = t.meta.plan_context as {
    placements: Record<string, unknown[]>;
    placements_omitted: Record<string, number>;
  };
  plan.placements['c-ds-5220'] = [];
  plan.placements_omitted['c-ds-5220'] = 2;
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  await expandSearch(container);
  expect(
    screen.getByText(
      'DS 5220：方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。',
    ),
  ).toBeVisible();
  expect(
    screen.getByText('另有 2 处位置未列出，请到培养方案页核对完整规则。'),
  ).toBeVisible();
  const source = screen.getByRole('link', { name: '方案官方目录来源' });
  expect(source).toHaveAttribute('target', '_blank');
  expect(source).toHaveAttribute('rel', 'noopener noreferrer');
});
it('notice codes the page does not know show nothing', () => {
  const t = fixtureTurn('alias-cs-6140').turn;
  if (t.meta?.kind !== 'ok') throw Error('fixture');
  t.meta.notices = ['future_notice', 'program_schedule_unverified'];
  const { container } = render(<SearchConversation {...props()} turns={[t]} />);
  expect(container.querySelectorAll('[data-kind="notice"]')).toHaveLength(1);
});
it('followups wait until the last turn has ended, and the status line says how it ended', () => {
  const t = fixtureTurn('alias-cs-6140').turn,
    p = props();
  const status = () =>
    screen.getByRole('status', { name: '回答状态' }).textContent;
  const { rerender } = render(
    <SearchConversation {...p} turns={[{ ...t, status: 'answering' }]} busy />,
  );
  expect(screen.queryByRole('group', { name: '接着问' })).toBeNull();
  rerender(<SearchConversation {...p} turns={[t]} />);
  expect(screen.getByRole('group', { name: '接着问' })).toBeVisible();
  expect(status()).toBe('回答完成。');
  const stopped = fixtureTurn('model-error').turn;
  expect(stopped.status).toBe('stopped');
  rerender(<SearchConversation {...p} turns={[stopped]} />);
  expect(status()).toBe('回答没有完成。');
});
it('the saved rating is pressed and the other is not', async () => {
  const p = props();
  p.onFeedback.mockImplementation((vote) =>
    Promise.resolve({ answer_id: vote.answer_id, rating: vote.rating }),
  );
  render(
    <SearchConversation
      {...p}
      turns={[fixtureTurn('feedback-receipt').turn]}
      feedbackEnabled
    />,
  );
  const up = await screen.findByRole('button', { name: '有帮助' }),
    down = screen.getByRole('button', { name: '没帮助' });
  expect(up).toHaveAttribute('aria-pressed', 'false');
  await userEvent.setup().click(up);
  await waitFor(() => expect(up).toHaveAttribute('aria-pressed', 'true'));
  expect(down).toHaveAttribute('aria-pressed', 'false');
});
it.each([
  ['flag off', false, true, 'done'],
  ['save off', true, false, 'done'],
  ['answering', true, true, 'answering'],
  ['stopped', true, true, 'stopped'],
] as const)(
  'feedback gate %s never shows controls',
  async (_label, feedbackEnabled, allowSave, status) => {
    const turn = { ...fixtureTurn('feedback-receipt').turn, allowSave, status };
    const { container } = render(
      <SearchConversation
        {...props()}
        turns={[turn]}
        feedbackEnabled={feedbackEnabled}
      />,
    );
    await act(async () => {});
    expect(container.querySelector('[aria-label="回答反馈"]')).toBeNull();
  },
);
it('feedback hash mismatch and malformed receipt cannot expose controls', async () => {
  const turn = fixtureTurn('feedback-receipt').turn;
  const digest = vi.spyOn(crypto.subtle, 'digest');
  const { rerender } = render(
    <SearchConversation
      {...props()}
      turns={[{ ...turn, text: turn.text + 'altered' }]}
      feedbackEnabled
    />,
  );
  await waitFor(() => expect(digest).toHaveBeenCalled());
  await act(async () => {
    await digest.mock.results[0]!.value;
  });
  expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
  rerender(
    <SearchConversation
      {...props()}
      turns={[
        { ...turn, receipt: { ...(turn.receipt as object), extra: true } },
      ]}
      feedbackEnabled
    />,
  );
  await act(async () => {});
  expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
});
it.each([
  ['answer_id', 'a'.repeat(31)],
  ['answer_id', 'A'.repeat(32)],
  ['answer_id', null],
  ['answer_sha256', 'a'.repeat(63)],
  ['answer_sha256', 'A'.repeat(64)],
  ['answer_sha256', 1],
  ['feedback_token', 'x'.repeat(42)],
  ['feedback_token', '+'.repeat(43)],
  ['feedback_token', 'x'.repeat(43) + '\n'],
  ['extra', true],
] as [string, unknown][])(
  'feedback malformed receipt field %s cannot enable controls even when the answer matches',
  async (field, bad) => {
    const t = fixtureTurn('feedback-receipt').turn;
    const digest = vi.spyOn(crypto.subtle, 'digest');
    const raw = { ...(t.receipt as object), [field]: bad };
    render(
      <SearchConversation
        {...props()}
        turns={[{ ...t, receipt: raw }]}
        feedbackEnabled
      />,
    );
    await act(async () => {
      await Promise.all(digest.mock.results.map((r) => r.value));
    });
    expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
  },
);
it('feedback synchronous lock prevents duplicate submission and only exact success changes the recorded rating', async () => {
  const turn = fixtureTurn('feedback-receipt').turn;
  let release!: (v: unknown) => void;
  const p = props();
  p.onFeedback.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  render(<SearchConversation {...p} turns={[turn]} feedbackEnabled />);
  const up = await screen.findByRole('button', { name: '有帮助' }),
    down = screen.getByRole('button', { name: '没帮助' });
  const user = userEvent.setup();
  await user.click(up);
  await user.click(down);
  expect(p.onFeedback).toHaveBeenCalledTimes(1);
  expect(up).toBeDisabled();
  expect(down).toBeDisabled();
  const vote = p.onFeedback.mock.calls[0]![0];
  expect(Object.keys(vote).sort()).toEqual([
    'answer_id',
    'answer_sha256',
    'feedback_token',
    'rating',
  ]);
  await act(async () => {
    release({ answer_id: vote.answer_id, rating: 'down' });
  });
  expect(up).toHaveAttribute('aria-pressed', 'false');
  expect(down).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByText('反馈响应校验失败；未标记为成功。')).toBeVisible();
});
it('changing receipt/text while digest is pending never enables stale feedback', async () => {
  const turn = fixtureTurn('feedback-receipt').turn;
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(turn.text),
  );
  let release!: (value: ArrayBuffer) => void;
  vi.spyOn(crypto.subtle, 'digest').mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const { rerender } = render(
    <SearchConversation {...props()} turns={[turn]} feedbackEnabled />,
  );
  rerender(
    <SearchConversation
      {...props()}
      turns={[{ ...turn, allowSave: false }]}
      feedbackEnabled
    />,
  );
  await act(async () => {
    release(digest);
  });
  expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
});
it('feedback unmount discards late vote results', async () => {
  let release!: (v: unknown) => void;
  const p = props();
  p.onFeedback.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const { unmount, container } = render(
    <SearchConversation
      {...p}
      turns={[fixtureTurn('feedback-receipt').turn]}
      feedbackEnabled
    />,
  );
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: '有帮助' }));
  const vote = p.onFeedback.mock.calls[0]![0];
  unmount();
  await act(async () => {
    release({ answer_id: vote.answer_id, rating: vote.rating });
  });
  expect(container).toBeEmptyDOMElement();
});
it.each([
  'alias-cs-6140',
  'plan-ds-align',
  'feedback-receipt',
  'refused-409-plan-stale',
  'answering',
])('search axe has no violations %s', async (name) => {
  const turn = fixtureTurn(
    name === 'answering' ? 'alias-cs-6140' : name,
    1,
    true,
  ).turn;
  if (name === 'answering') turn.status = 'answering';
  const { container } = render(
    <SearchConversation
      {...props()}
      turns={[turn]}
      feedbackEnabled={name === 'feedback-receipt'}
      busy={name === 'answering'}
    />,
  );
  if (name === 'feedback-receipt')
    await screen.findByRole('button', { name: '有帮助' });
  await expandSearch(container);
  expect(
    (await axe(container, { rules: { 'color-contrast': { enabled: false } } }))
      .violations,
  ).toEqual([]);
});
