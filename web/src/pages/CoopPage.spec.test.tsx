import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { CoopPageProps, CoopRecord, SubmitOutcome } from '../api/coop';
import guest from '../fixtures/coop/list-guest.json';
import member0 from '../fixtures/coop/list-member-0.json';
import member1 from '../fixtures/coop/list-member-1.json';
import member2 from '../fixtures/coop/list-member-2.json';
import pending from '../fixtures/coop/upload-pending.json';
import dupPending from '../fixtures/coop/upload-duplicate-pending.json';
import approved from '../fixtures/coop/upload-duplicate-approved.json';
import published from '../fixtures/coop/upload-duplicate-published.json';
import rejected from '../fixtures/coop/upload-duplicate-rejected.json';
import unauthorized from '../fixtures/coop/upload-401-unknown-user.json';
import invalid from '../fixtures/coop/upload-422-duration.json';
import unavailable from '../fixtures/coop/upload-503-no-moderation.json';
import { CoopPage } from './CoopPage';

function page(overrides: Partial<CoopPageProps> = {}) {
  const input: CoopPageProps = {
    viewer: { kind: 'member', contributionCount: 0 },
    list: { status: 'ready', records: member0.body as CoopRecord[] },
    onLogin: vi.fn(),
    onRetryList: vi.fn(),
    onSubmit: vi.fn(
      async () => ({ ok: true, result: pending.body }) as SubmitOutcome,
    ),
    ...overrides,
  };
  return {
    ...render(
      <MemoryRouter>
        <CoopPage {...input} />
      </MemoryRouter>,
    ),
    input,
  };
}
function form() {
  return screen.getByRole('form', { name: '分享你的 Co-op 经验' });
}
function field(label: RegExp) {
  return within(form()).getByLabelText(label);
}
it('native badInput with an empty DOM value is invalid, not an omitted duration', async () => {
  const { input } = page();
  await required();
  const duration = field(/^时长/);
  if (!(duration instanceof HTMLInputElement))
    throw new Error('Expected the native duration input');
  expect(duration).toHaveValue(null);
  // jsdom sanitizes incomplete numeric strings without emulating the browser's
  // editing buffer. Model the badInput flag observed with real keyboard input.
  const validity = vi.spyOn(duration, 'validity', 'get').mockReturnValue({
    badInput: true,
    customError: false,
    patternMismatch: false,
    rangeOverflow: false,
    rangeUnderflow: false,
    stepMismatch: false,
    tooLong: false,
    tooShort: false,
    typeMismatch: false,
    valid: false,
    valueMissing: false,
  });
  try {
    await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(input.onSubmit).not.toHaveBeenCalled();
    expect(duration).toHaveAccessibleDescription(
      '时长只能是 1–8 的整数，或留空。',
    );
    expect(duration).toHaveAttribute('aria-invalid', 'true');
    expect(field(/^公司/)).toHaveValue('  Example Co.  ');
    expect(screen.getByRole('status', { name: '投稿结果' })).toHaveFocus();
  } finally {
    validity.mockRestore();
  }
});
async function required() {
  const user = userEvent.setup();
  await user.type(field(/^公司/), '  Example Co.  ');
  await user.type(field(/^职位/), '  Data Co-op  ');
  return user;
}
const interviewLock = '这条有面试细节：你分享的经验有 1 条公开后解锁';
const salaryLock = '这条有薪资区间：你分享的经验有 2 条公开后解锁';
it('keyword search is trimmed and case-insensitive', async () => {
  page();
  await userEvent.type(screen.getByRole('searchbox'), '  hEaLtH  ');
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(
    screen.getByRole('article', { name: /Sample Health/ }),
  ).toBeInTheDocument();
});
it('injected viewer scope resets filters and removes private details', async () => {
  const { input, rerender } = page({
    viewer: { kind: 'member', contributionCount: 2 },
    list: { status: 'ready', records: member2.body as CoopRecord[] },
  });
  await userEvent.type(screen.getByRole('searchbox'), 'health');
  expect(screen.getAllByRole('article')).toHaveLength(1);
  rerender(
    <MemoryRouter>
      <CoopPage
        {...input}
        viewer={{ kind: 'guest' }}
        list={{ status: 'ready', records: guest.body as CoopRecord[] }}
      />
    </MemoryRouter>,
  );
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(screen.getByRole('searchbox')).toHaveValue('');
  expect(screen.queryByText('$40-45/hr')).not.toBeInTheDocument();
});
it('industry and keyword filters intersect and clear restores focus', async () => {
  page();
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: /^筛选行业/ }));
  await user.click(screen.getByRole('option', { name: '量化 / 金融科技' }));
  await user.type(screen.getByRole('searchbox'), 'health');
  expect(screen.queryAllByRole('article')).toHaveLength(0);
  await user.click(screen.getByRole('button', { name: '查看全部记录' }));
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(screen.getByRole('searchbox')).toHaveValue('');
  expect(screen.getByRole('searchbox')).toHaveFocus();
  expect(screen.getByRole('combobox', { name: /^筛选行业/ })).toHaveTextContent(
    '全部行业',
  );
});
for (const [name, count, fixture] of [
  ['guest', null, guest],
  ['member0', 0, member0],
  ['member1', 1, member1],
  ['member2', 2, member2],
] as const) {
  it(`API fixture visibility and exact lock placement for ${name}`, () => {
    page({
      viewer:
        count === null
          ? { kind: 'guest' }
          : { kind: 'member', contributionCount: count },
      list: { status: 'ready', records: fixture.body as CoopRecord[] },
    });
    expect(screen.getAllByRole('article')).toHaveLength(4);
    for (const record of fixture.body) {
      const card = screen.getByRole('article', {
        name: new RegExp(record.company),
      });
      expect(within(card).queryByText(interviewLock) !== null).toBe(
        record.visibility_level === 1 &&
          !record.interview_summary &&
          !record.technical_questions,
      );
      expect(within(card).queryByText(salaryLock) !== null).toBe(
        record.visibility_level === 2 && !record.salary_range_usd,
      );
      for (const key of [
        'interview_summary',
        'technical_questions',
        'salary_range_usd',
      ] as const)
        if (record[key])
          expect(within(card).getByText(record[key]!)).toBeInTheDocument();
    }
    for (const record of member2.body)
      for (const key of [
        'interview_summary',
        'technical_questions',
        'salary_range_usd',
      ] as const)
        if (
          record[key] &&
          ((count ?? 0) === 0 || (count === 1 && key === 'salary_range_usd'))
        )
          expect(screen.queryByText(record[key]!)).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole('article', { name: /Demo Robotics/ }),
      ).queryByText(/这条有/),
    ).not.toBeInTheDocument();
  });
}
it('salary-tier records do not invent interview availability', () => {
  page({
    list: {
      status: 'ready',
      records: [
        {
          ...member0.body[0]!,
          visibility_level: 2,
          interview_summary: null,
          technical_questions: null,
        } as CoopRecord,
      ],
    },
  });
  expect(screen.queryByText(interviewLock)).not.toBeInTheDocument();
  expect(screen.getByText(salaryLock)).toBeInTheDocument();
});
it('returned interview fields use collapsed native details', async () => {
  page({ list: { status: 'ready', records: member1.body as CoopRecord[] } });
  const card = screen.getByRole('article', { name: /Sample Health/ });
  const text = member1.body.find(
    (record) => record.coop_id === 'coop-seed-health',
  )!.interview_summary!;
  expect(within(card).getByText(text)).not.toBeVisible();
  await userEvent.click(within(card).getByText('面试经过'));
  expect(within(card).getByText(text)).toBeVisible();
});
it('guest only sees login callbacks, not upload fields', async () => {
  const { input } = page({ viewer: { kind: 'guest' } });
  expect(
    screen.queryByRole('form', { name: '分享你的 Co-op 经验' }),
  ).not.toBeInTheDocument();
  expect(screen.getByText('用 NEU 邮箱登录后才能分享。')).toBeInTheDocument();
  const login = screen.getAllByRole('button', { name: /^登录$/ });
  await userEvent.click(login[0]!);
  await userEvent.click(login[1]!);
  expect(input.onLogin).toHaveBeenCalledTimes(2);
});
it('error is separate from empty and retry invokes the injected callback', async () => {
  const { input } = page({ list: { status: 'error' } });
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Co-op 列表暂时加载不了，请稍后重试。',
  );
  expect(screen.queryByText(/还没有/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(input.onRetryList).toHaveBeenCalledExactlyOnceWith();
});
it('loading is busy and not empty', () => {
  page({ list: { status: 'loading' } });
  expect(
    screen.getByRole('region', { name: 'Co-op 经历列表' }),
  ).toHaveAttribute('aria-busy', 'true');
  expect(screen.getByText('正在加载')).toBeInTheDocument();
  expect(screen.queryByText(/还没有/)).not.toBeInTheDocument();
});
it('ready empty has the specified invitation', () => {
  page({ list: { status: 'ready', records: [] } });
  expect(
    screen.getByText('还没有可以公开的 Co-op 经验，欢迎分享第一条。'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it.each(['公司', '职位'])(
  'whitespace-only %s prevents submission and connects its field error',
  async (label) => {
    const { input } = page();
    await required();
    fireEvent.change(field(new RegExp(`^${label}`)), {
      target: { value: '   ' },
    });
    await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(input.onSubmit).not.toHaveBeenCalled();
    expect(field(new RegExp(`^${label}`))).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(field(new RegExp(`^${label}`))).toHaveAccessibleDescription(
      '公司和职位是必填项。',
    );
    expect(screen.getByRole('status', { name: '投稿结果' })).toHaveFocus();
  },
);
it.each(['9', '0', '2.5'])(
  'invalid duration %s prevents submission',
  async (value) => {
    const { input } = page();
    await required();
    fireEvent.change(field(/^时长/), { target: { value } });
    await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(input.onSubmit).not.toHaveBeenCalled();
    expect(field(/^时长/)).toHaveAccessibleDescription(
      '时长只能是 1–8 的整数，或留空。',
    );
  },
);
it('request has exact trimmed keys, nullable blanks and deduplicated courses from all delimiters', async () => {
  const { input } = page();
  const user = await required();
  await user.type(field(/^Co-op 学期/), '  Fall 2026  ');
  await user.selectOptions(field(/^行业$/), 'big_tech');
  await user.type(
    field(/^相关课程/),
    ' CS 6140, DS 5220，CS 6140、CS 5800,, 、',
  );
  await user.type(field(/^面试经过/), '  合成面试  ');
  await user.type(field(/^技术问题/), '   ');
  await user.type(field(/^薪资区间/), '  $30/hr  ');
  await user.click(screen.getByRole('button', { name: '提交经验' }));
  expect(input.onSubmit).toHaveBeenCalledExactlyOnceWith({
    company: 'Example Co.',
    role: 'Data Co-op',
    coop_term: 'Fall 2026',
    industry: 'big_tech',
    duration_months: null,
    related_courses: ['CS 6140', 'DS 5220', 'CS 5800'],
    interview_summary: '合成面试',
    technical_questions: null,
    salary_range_usd: '$30/hr',
  });
});
it('all optional empty fields become null or an empty course array', async () => {
  const { input } = page();
  await required();
  await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
  expect(input.onSubmit).toHaveBeenCalledExactlyOnceWith({
    company: 'Example Co.',
    role: 'Data Co-op',
    coop_term: null,
    industry: null,
    duration_months: null,
    related_courses: [],
    interview_summary: null,
    technical_questions: null,
    salary_range_usd: null,
  });
});
it.each([/^面试经过/, /^技术问题/, /^薪资区间/])(
  'text over 10000 Unicode characters is rejected for %s',
  async (label) => {
    const { input } = page();
    await required();
    fireEvent.change(field(label), { target: { value: '文'.repeat(10001) } });
    await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(input.onSubmit).not.toHaveBeenCalled();
    expect(field(label)).toHaveAccessibleDescription('最多 10,000 字。');
  },
);
it('10000 astral characters match backend character limits instead of UTF16 code units', async () => {
  const { input } = page();
  await required();
  fireEvent.change(field(/^面试经过/), {
    target: { value: '𠀀'.repeat(10000) },
  });
  await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
  expect(input.onSubmit).toHaveBeenCalledTimes(1);
});
it('in-flight submission disables the button and suppresses double submit', async () => {
  let resolve: ((outcome: SubmitOutcome) => void) | undefined;
  const onSubmit = vi.fn(
    () =>
      new Promise<SubmitOutcome>((done) => {
        resolve = done;
      }),
  );
  page({ onSubmit });
  await required();
  await userEvent.dblClick(screen.getByRole('button', { name: '提交经验' }));
  expect(screen.getByRole('button', { name: '提交中' })).toBeDisabled();
  fireEvent.submit(form());
  expect(onSubmit).toHaveBeenCalledTimes(1);
  await act(async () => {
    resolve?.({
      ok: true,
      result: pending.body as Extract<SubmitOutcome, { ok: true }>['result'],
    });
  });
});
for (const [fixture, message] of [
  [pending, '已私有收集，等待人工脱敏审核；尚未公开，也未新增贡献奖励。'],
  [dupPending, '已私有收集，等待人工脱敏审核；尚未公开，也未新增贡献奖励。'],
  [approved, '已审核，等待至少两个不同贡献者的同组经历齐备后公开。'],
  [published, '已审核并公开；贡献奖励以服务端计数为准。'],
  [rejected, '此提交已被审核拒绝；未公开，请联系审核员处理。'],
] as const) {
  it(`success clears every field and focuses exact outcome for ${fixture.case}`, async () => {
    page({
      onSubmit: vi.fn(
        async () => ({ ok: true, result: fixture.body }) as SubmitOutcome,
      ),
    });
    const user = await required();
    await user.type(field(/^Co-op 学期/), 'Fall 2026');
    await user.selectOptions(field(/^行业$/), 'other');
    await user.type(field(/^时长/), '6');
    await user.type(field(/^相关课程/), 'CS 6140');
    await user.type(field(/^面试经过/), '面试');
    await user.type(field(/^技术问题/), '问题');
    await user.type(field(/^薪资区间/), '$30/hr');
    await user.click(screen.getByRole('button', { name: '提交经验' }));
    const result = screen.getByRole('status', { name: '投稿结果' });
    expect(result).toHaveTextContent(message);
    expect(result).toHaveTextContent(fixture.body.coop_id);
    expect(result).toHaveFocus();
    expect(
      result.textContent?.includes('重复提交，保留原记录（内容未替换）。'),
    ).toBe(fixture.body.duplicate);
    for (const control of form().querySelectorAll('input, textarea, select'))
      expect(control).toHaveValue(
        control.getAttribute('type') === 'number' ? null : '',
      );
    expect(
      screen.getByText('已公开贡献：0 条 · 当前等级 0'),
    ).toBeInTheDocument();
    expect(screen.getAllByText(salaryLock)).toHaveLength(2);
  });
}
for (const [name, outcome, message] of [
  [
    '401',
    { ok: false, status: 401, body: unauthorized.body },
    '登录已经失效，请重新登录后再提交。',
  ],
  [
    '422',
    { ok: false, status: 422, body: invalid.body },
    '有一项不符合要求，请检查后再提交。',
  ],
  [
    '503',
    { ok: false, status: 503, body: unavailable.body },
    '投稿暂时提交不了，请稍后再试。你填的内容还在。',
  ],
  [
    'network',
    { ok: false, status: 503, body: null },
    '投稿暂时提交不了，请稍后再试。你填的内容还在。',
  ],
  [
    '504',
    { ok: false, status: 504, body: null },
    '投稿暂时提交不了，请稍后再试。你填的内容还在。',
  ],
  [
    'other',
    {
      ok: false as const,
      status: 500,
      body: {
        detail: 'PRIVATE ENGLISH',
        error_type: 'server_error',
        status_code: 500,
      },
    },
    '提交没有成功，请稍后再试。',
  ],
] as const) {
  it(`failure ${name} preserves fields, focuses fixed Chinese and never shows raw detail`, async () => {
    const { input } = page({ onSubmit: vi.fn(async () => outcome) });
    await required();
    await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    const result = screen.getByRole('status', { name: '投稿结果' });
    expect(result).toHaveTextContent(message);
    expect(result).toHaveFocus();
    expect(field(/^公司/)).toHaveValue('  Example Co.  ');
    if (outcome.body)
      expect(screen.queryByText(outcome.body.detail)).not.toBeInTheDocument();
    if (name === '422')
      expect(field(/^时长/)).toHaveAccessibleDescription(
        '有一项不符合要求，请检查后再提交。',
      );
    if (name === '401') {
      await userEvent.click(
        within(result).getByRole('button', { name: '登录' }),
      );
      expect(input.onLogin).toHaveBeenCalledTimes(1);
    }
  });
}
it.each([
  'company',
  'role',
  'coop_term',
  'industry',
  'duration_months',
  'related_courses',
  'interview_summary',
  'technical_questions',
  'salary_range_usd',
])('422 safely maps known field %s without echoing detail', async (name) => {
  page({
    onSubmit: vi.fn(async () => ({
      ok: false as const,
      status: 422,
      body: {
        detail: `${name}: PRIVATE VALUE`,
        error_type: 'invalid_input',
        status_code: 422,
      },
    })),
  });
  await required();
  await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
  const control = form().querySelector(`[name="${name}"]`);
  expect(control).toHaveAttribute('aria-invalid', 'true');
  expect(control).toHaveAccessibleDescription(
    '有一项不符合要求，请检查后再提交。',
  );
  expect(screen.queryByText(/PRIVATE VALUE/)).not.toBeInTheDocument();
});
it('unknown 422 field remains generic with no invalid field', async () => {
  page({
    onSubmit: vi.fn(async () => ({
      ok: false as const,
      status: 422,
      body: {
        detail: '__proto__: PRIVATE VALUE',
        error_type: 'invalid_input',
        status_code: 422,
      },
    })),
  });
  await required();
  await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
  expect(form().querySelector('[aria-invalid="true"]')).toBeNull();
  expect(screen.queryByText(/PRIVATE VALUE/)).not.toBeInTheDocument();
});
it('rejected callback does not leak its message or discard inputs', async () => {
  page({
    onSubmit: vi.fn(async () => {
      throw new Error('PRIVATE CALLBACK');
    }),
  });
  await required();
  await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
  expect(screen.getByRole('status', { name: '投稿结果' })).toHaveTextContent(
    '投稿暂时提交不了',
  );
  expect(screen.queryByText(/PRIVATE CALLBACK/)).not.toBeInTheDocument();
  expect(field(/^公司/)).toHaveValue('  Example Co.  ');
});
for (const mode of ['guest', 'member2', 'invalid'] as const)
  it(`axe has no violations for Co-op ${mode}`, async () => {
    const { container } = page(
      mode === 'guest'
        ? { viewer: { kind: 'guest' } }
        : mode === 'member2'
          ? {
              viewer: { kind: 'member', contributionCount: 2 },
              list: { status: 'ready', records: member2.body as CoopRecord[] },
            }
          : {},
    );
    if (mode === 'invalid')
      await userEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(
      (
        await axe(container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });
