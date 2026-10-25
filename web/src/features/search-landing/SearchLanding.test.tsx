import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import { expect, it, vi } from 'vitest';
import { SearchLanding } from './SearchLanding';
import {
  landingExpected,
  settledLanding,
  readLanding,
  failure,
  ready,
} from './landingTestUtils';
import { landingFixture, landingSources } from '../../fixtures/landingDemo';
import { SAMPLE_QUESTIONS } from '../../models/landing';

const callbacks = () => ({
  onAsk: vi.fn(),
  onOpenProgram: vi.fn(),
  onViewCourse: vi.fn(),
  onOpenCoop: vi.fn(),
  onRetry: vi.fn(),
});
const guest = () => settledLanding(landingSources('guest'));
const fixtureCopy = <T,>(name: string) =>
  structuredClone(landingFixture(name).body) as T;
it('freezes 27 independent expected scenes and the production source manifest', () => {
  expect(landingExpected).toHaveLength(27);
  for (const e of landingExpected)
    expect(landingSources(e.name)).toEqual(e.sources);
});
it.each(landingExpected)(
  'landing golden $name exact text order and callback IDs',
  (e) => {
    const { container } = render(
      <SearchLanding {...settledLanding(e.sources)} {...callbacks()} />,
    );
    expect(readLanding(container)).toEqual(e.visible);
    expect(container.querySelector('a')).toBeNull();
  },
);
it('each landing button sends its own exact ID or query, not a display label', async () => {
  const cb = callbacks(),
    user = userEvent.setup();
  render(<SearchLanding {...guest()} {...cb} />);
  await user.click(screen.getByRole('button', { name: 'AAI · 4 门课' }));
  expect(cb.onOpenProgram).toHaveBeenCalledExactlyOnceWith('aai-ms');
  await user.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  expect(cb.onViewCourse).toHaveBeenCalledExactlyOnceWith('c-cs-5010');
  await user.click(screen.getByRole('button', { name: '去看看' }));
  expect(cb.onOpenCoop).toHaveBeenCalledOnce();
  for (const q of SAMPLE_QUESTIONS)
    await user.click(screen.getByRole('button', { name: q.label }));
  expect(cb.onAsk.mock.calls.map(([q]) => q)).toEqual(
    SAMPLE_QUESTIONS.map((q) => q.query),
  );
});
it.each(['programs', 'coop', 'aai-ms', 'cs-ms', 'ds-ms'])(
  'loading %s keeps independent ready sections and waits for the whole starter row',
  (key) => {
    const data = guest();
    if (key === 'programs' || key === 'coop') data[key] = { status: 'loading' };
    else data.curricula[key] = { status: 'loading' };
    const { container, rerender } = render(
      <SearchLanding {...data} {...callbacks()} />,
    );
    expect(screen.getByLabelText('发现课程与经验')).toHaveAttribute(
      'aria-busy',
      'true',
    );
    expect(screen.getByText('正在加载推荐内容…')).toBeInTheDocument();
    expect(container.querySelector('[data-kind="program"]') !== null).toBe(
      key !== 'programs',
    );
    expect(container.querySelector('[data-kind="coop"]') !== null).toBe(
      key !== 'coop',
    );
    expect(container.querySelector('[data-kind="starter"]') !== null).toBe(
      key === 'coop',
    );
    rerender(<SearchLanding {...guest()} {...callbacks()} />);
    expect(screen.queryByText('正在加载推荐内容…')).not.toBeInTheDocument();
    expect(screen.getByLabelText('发现课程与经验')).toHaveAttribute(
      'aria-busy',
      'false',
    );
  },
);
it('a missing required curriculum is loading, irrelevant keys are ignored, failures and pending coexist once', async () => {
  const data = guest(),
    cb = callbacks();
  delete data.curricula['cs-ms'];
  data.curricula['other'] = { status: 'loading' };
  data.coop = failure(503);
  const { container, rerender } = render(<SearchLanding {...data} {...cb} />);
  expect(container.querySelector('[data-kind="starter"]')).toBeNull();
  expect(screen.getByText('正在加载推荐内容…')).toBeInTheDocument();
  expect(screen.getAllByText('部分内容暂时没加载出来。')).toHaveLength(1);
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '重新加载' }));
  expect(cb.onRetry).toHaveBeenCalledOnce();
  data.programs = failure(503);
  data.coop = failure(504);
  rerender(<SearchLanding {...data} {...cb} />);
  expect(screen.queryByText('正在加载推荐内容…')).toBeNull();
  expect(screen.getAllByText('部分内容暂时没加载出来。')).toHaveLength(1);
});
it('a listed program that is not featured never gets a starter card, even with a curriculum to pick from', () => {
  const data = guest();
  data.curricula['pjm-ms'] = ready({
    ...fixtureCopy<object>('curriculum-cs-ms'),
    program_id: 'pjm-ms',
  });
  const { container } = render(<SearchLanding {...data} {...callbacks()} />);
  expect(
    readLanding(container)
      .filter((item) => item.kind === 'starter')
      .map((item) => (item as { code: string }).code),
  ).toEqual(['AAI 6600', 'CS 5010']);
});
it.each([0, 401, 403, 404, 422])(
  'definite failure %s never advertises a retry',
  (status) => {
    const data = guest();
    data.programs = failure(status);
    data.coop = failure(status);
    data.curricula['cs-ms'] = { status: 'loading' };
    render(<SearchLanding {...data} {...callbacks()} />);
    expect(screen.queryByRole('button', { name: '重新加载' })).toBeNull();
    expect(screen.queryByText('正在加载推荐内容…')).toBeNull();
  },
);
it.each([408, 429, 500, 502, 503, 504])(
  'temporary failure %s displays one retry without hiding good Co-op content',
  (status) => {
    const data = guest();
    data.programs = failure(status);
    render(<SearchLanding {...data} {...callbacks()} />);
    expect(screen.getAllByRole('button', { name: '重新加载' })).toHaveLength(1);
    expect(
      screen.getByRole('heading', { name: '最近的 Co-op 经验' }),
    ).toBeInTheDocument();
  },
);
it('invalid program list or empty list ignores dependent failures and loading while good Co-op stays', () => {
  const data = guest();
  data.programs = ready({ bad: true });
  data.curricula['aai-ms'] = failure(503);
  data.curricula['cs-ms'] = { status: 'loading' };
  const { rerender } = render(<SearchLanding {...data} {...callbacks()} />);
  expect(screen.queryByText('部分内容暂时没加载出来。')).toBeNull();
  expect(screen.queryByText('正在加载推荐内容…')).toBeNull();
  expect(
    screen.getByRole('heading', { name: '最近的 Co-op 经验' }),
  ).toBeInTheDocument();
  data.programs = ready([]);
  rerender(<SearchLanding {...data} {...callbacks()} />);
  expect(screen.queryByText('部分内容暂时没加载出来。')).toBeNull();
});
it('API text stays literal in prefix code name company and role, with no body anchors or HTML', () => {
  const text =
    '<b>x</b> [链接](https://example.com) javascript:alert(1)\r\nline two\rjoined';
  const data = guest();
  data.programs = ready([
    {
      program_id: 'aai-ms',
      prefix: text,
      full_name: text,
      course_count: 1,
      plan_count: 0,
    },
  ]);
  data.curricula['aai-ms'] = ready({
    program_id: 'aai-ms',
    prefix: text,
    full_name: text,
    notes: null,
    semesters: [
      {
        semester: 1,
        courses: [
          {
            course_id: 'literal',
            primary_code: text,
            primary_name: text,
            requirement_type: 'core',
          },
        ],
      },
    ],
    plans: [],
    plan_schema_available: true,
  });
  data.coop = ready([{ company: text, role: text, visibility_level: 0 }]);
  const { container } = render(<SearchLanding {...data} {...callbacks()} />);
  expect(container.querySelectorAll('b,a,img,script')).toHaveLength(0);
  expect(container.querySelector('[data-name]')?.textContent).toBe(
    text.replaceAll('\r', ''),
  );
  expect(container.querySelector('[data-company]')?.textContent).toBe(
    text.replaceAll('\r', ''),
  );
  expect(
    container.querySelector('[data-kind="program"]')?.textContent,
  ).toContain('javascript:alert(1) line two joined');
});
it('every card and Co-op value drops CR and keeps LF, and 查看 names the code on one line', () => {
  const text = 'A<b>1</b>\r\nB\rC';
  const shown = 'A<b>1</b>\nBC';
  const data = guest();
  const curriculum = fixtureCopy<{
    prefix: string;
    semesters: { courses: Record<string, unknown>[] }[];
  }>('curriculum-cs-ms');
  curriculum.prefix = text;
  curriculum.semesters[0]!.courses[0]!.primary_code = text;
  curriculum.semesters[0]!.courses[0]!.primary_name = text;
  data.curricula['cs-ms'] = ready(curriculum);
  const rows = fixtureCopy<Record<string, unknown>[]>('coop-guest');
  rows[0]!.company = text;
  rows[0]!.role = text;
  data.coop = ready(rows);
  const { container } = render(<SearchLanding {...data} {...callbacks()} />);
  const card = container.querySelectorAll('[data-kind="starter"]')[1]!;
  for (const field of ['[data-code]', '[data-prefix]', '[data-name]'])
    expect(card.querySelector(field)!.textContent).toBe(shown);
  expect(container.querySelector('[data-company]')!.textContent).toBe(shown);
  expect(container.querySelector('[data-role]')!.textContent).toBe(shown);
  // The attribute itself: a query by accessible name would fold the whitespace.
  expect(
    container
      .querySelectorAll('[data-kind="view"]')[1]!
      .getAttribute('aria-label'),
  ).toBe('查看 A<b>1</b> B C');
});
it('the title is a level-2 heading and the four subheadings level 3 (spec 8)', () => {
  render(<SearchLanding {...guest()} {...callbacks()} />);
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
    '问一门课，或者一个选课问题',
  );
  expect(
    screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
  ).toEqual(['按培养方案浏览', '入门推荐', '最近的 Co-op 经验', '试试这样问']);
});
it('the Co-op rows are one list, each company in strong (spec 8)', () => {
  render(<SearchLanding {...guest()} {...callbacks()} />);
  const list = screen.getByRole('list');
  expect(within(list).getAllByRole('listitem')).toHaveLength(2);
  expect(list.querySelectorAll('strong[data-company]')).toHaveLength(2);
});
it('every program button sends its own ID, in the API’s order (spec 12.5)', () => {
  const cb = callbacks();
  const { container } = render(<SearchLanding {...guest()} {...cb} />);
  for (const button of container.querySelectorAll<HTMLElement>(
    '[data-kind="program"]',
  ))
    fireEvent.click(button);
  expect(cb.onOpenProgram.mock.calls.map(([id]) => id)).toEqual([
    'aai-ms',
    'cs-ms',
    'ds-ms',
    'pjm-ms',
  ]);
});
it('the loading line comes after the three blocks and before the notice (spec 6)', () => {
  const data = guest();
  data.curricula['cs-ms'] = { status: 'loading' };
  data.coop = failure(503);
  const { container } = render(<SearchLanding {...data} {...callbacks()} />);
  const programs = container.querySelector('[data-kind="program"]')!;
  const line = screen.getByText('正在加载推荐内容…');
  const notice = screen.getByText('部分内容暂时没加载出来。');
  expect(
    programs.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    line.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
// The golden items are read from data-kind elements, so text outside them (an icon in its own span) would pass the
// comparison above: nothing else may show, and no emoji or arrow (spec 9.2, 14.2).
it.each(landingExpected)(
  'landing $name shows no text outside the golden items, and no emoji or arrow',
  (e) => {
    const { container } = render(
      <SearchLanding {...settledLanding(e.sources)} {...callbacks()} />,
    );
    const text = container.textContent ?? '';
    expect(text).not.toMatch(
      /[\u{FE0F}\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}]/u,
    );
    const items = [...container.querySelectorAll('[data-kind]')]
      .map((el) => el.textContent)
      .join('');
    expect(text.replace(/\s+/g, '')).toBe(items.replace(/\s+/g, ''));
  },
);
it.each(['guest', 'programs-503', 'coop-text-edge', 'loading'])(
  'landing axe %s',
  async (name) => {
    const data = guest();
    const props =
      name === 'loading'
        ? { ...data, programs: { status: 'loading' as const } }
        : settledLanding(landingSources(name));
    const { container } = render(<SearchLanding {...props} {...callbacks()} />);
    const result = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  },
);
