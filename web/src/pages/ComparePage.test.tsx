import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { ComparePageProps } from '../api/course';
import { ComparePage } from './ComparePage';
import cs5800 from '../fixtures/compare/course-cs-5800.json';
import cs6140 from '../fixtures/compare/course-cs-6140.json';
import ds5220 from '../fixtures/compare/course-ds-5220.json';
import cs5100 from '../fixtures/compare/course-cs-5100.json';
import cs7800 from '../fixtures/compare/course-cs-7800.json';
import unavailable from '../fixtures/compare/course-cs-5800-requisites-unavailable.json';
import e5800 from '../fixtures/compare/expected/course-cs-5800.json';
import e6140 from '../fixtures/compare/expected/course-cs-6140.json';
import e5220 from '../fixtures/compare/expected/course-ds-5220.json';
import e5100 from '../fixtures/compare/expected/course-cs-5100.json';
import e7800 from '../fixtures/compare/expected/course-cs-7800.json';
import eUnavailable from '../fixtures/compare/expected/course-cs-5800-requisites-unavailable.json';

const fixtures = [cs5800, cs6140, ds5220, cs5100];
function props(overrides: Partial<ComparePageProps> = {}): ComparePageProps {
  return {
    ids: fixtures.map((f) => f.body.course_id),
    columns: Object.fromEntries(
      fixtures.map((f) => [
        f.body.course_id,
        { status: 'ready', body: f.body },
      ]),
    ),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onReload: vi.fn(),
    ...overrides,
  };
}
function page(overrides: Partial<ComparePageProps> = {}) {
  const input = props(overrides);
  return {
    input,
    ...render(
      <MemoryRouter>
        <ComparePage {...input} />
      </MemoryRouter>,
    ),
  };
}
const normalized = (value: string | null) => value?.replace(/\s+/g, ' ').trim();
const bad = '这一项的数据格式不对，没有显示。';
for (const [fixture, expected] of [
  [cs5800, e5800],
  [cs6140, e6140],
  [ds5220, e5220],
  [cs5100, e5100],
  [cs7800, e7800],
  [unavailable, eUnavailable],
] as const) {
  it(`matches every golden header and cell for ${fixture.case}`, () => {
    page({
      ids: [fixture.body.course_id],
      columns: {
        [fixture.body.course_id]: { status: 'ready', body: fixture.body },
      },
    });
    const heads = screen.getAllByRole('columnheader');
    const head = heads[1]!;
    expect(head).toHaveTextContent(expected.header.code);
    expect(head).toHaveTextContent(expected.header.name);
    const label: Record<string, string> = {
      Term: '学期',
      Credits: '学分',
      Mode: '授课方式',
    };
    const mode: Record<string, string> = {
      'in person': '线下',
      hybrid: '混合',
      online: '线上',
      async: '异步',
    };
    for (const [key, value] of expected.header.chips)
      expect(head).toHaveTextContent(
        `${label[key!]} ${key === 'Mode' ? (mode[value!] ?? value) : value}`,
      );
    if (expected.header.notice)
      expect(head).toHaveTextContent(expected.header.notice);
    if (expected.header.credit_range_note)
      expect(head).toHaveTextContent(expected.header.credit_range_note);
    expect(
      within(head).getByRole('link', { name: `查看 ${expected.header.code}` }),
    ).toHaveAttribute(
      'href',
      `/course/${expected.header.code.replaceAll(' ', '-')}`,
    );
    for (const [name, calls] of Object.entries(expected.rows)) {
      const row = screen.getByRole('rowheader', { name }).closest('tr')!;
      const cell = within(row).getByRole('cell');
      const wanted =
        name === '主题' || name === '在培养方案里的位置'
          ? calls.filter((call) => call[0] !== 'main')
          : calls;
      const lines = Array.from(cell.querySelectorAll('[data-kind]')).map(
        (el) => [el.getAttribute('data-kind'), normalized(el.textContent)],
      );
      // Empty topics/programs use the ordinary main line rather than pills.
      const actual =
        name === '主题' || name === '在培养方案里的位置'
          ? lines.filter((line) => line[0] !== 'main')
          : lines;
      expect(actual, name).toEqual(
        wanted.map(([kind, text]) => [kind, normalized(text!)]),
      );
      if (name === '主题')
        for (const topic of expected.topics)
          expect(cell).toHaveTextContent(topic);
      if (name === '主题' && !expected.topics.length)
        expect(cell).toHaveTextContent('没有记录');
      if (name === '在培养方案里的位置')
        for (const placement of expected.program_context)
          for (const text of placement)
            if (text) expect(cell).toHaveTextContent(text);
    }
    const catalog = screen
      .getByRole('rowheader', { name: '官方目录描述' })
      .closest('tr')!;
    expect(
      within(catalog)
        .queryAllByRole('link')
        .map((link) => [link.textContent, link.getAttribute('href')]),
    ).toEqual(expected.links);
    const requisite = screen
      .getByRole('rowheader', { name: '先修／共修' })
      .closest('tr')!;
    expect(
      Array.from(requisite.querySelectorAll('[data-kind="main"]')).map(
        (el) => el.textContent,
      ),
    ).toEqual(expected.requisite_summary);
  });
}
it('uses only the first four ids without mutating the supplied list', () => {
  const ids = Object.freeze([
    ...fixtures.map((f) => f.body.course_id),
    cs7800.body.course_id,
  ]);
  page({ ids });
  expect(screen.getAllByRole('columnheader')).toHaveLength(5);
  expect(screen.queryByText(cs7800.body.primary_name)).not.toBeInTheDocument();
  expect(ids).toHaveLength(5);
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('combobox', { name: /按方案看/ }),
  ).not.toBeInTheDocument();
});
it('bad-cell damages only grading, while all other cells and columns remain usable', () => {
  page({
    columns: {
      [cs5800.body.course_id]: {
        status: 'ready',
        body: { ...cs5800.body, grading_components: 'not a list' },
      },
      [cs6140.body.course_id]: { status: 'ready', body: cs6140.body },
    },
    ids: [cs5800.body.course_id, cs6140.body.course_id],
  });
  expect(screen.getAllByText(bad)).toHaveLength(1);
  expect(
    within(
      screen.getByRole('rowheader', { name: '考核构成' }).closest('tr')!,
    ).getAllByRole('cell')[0],
  ).toHaveTextContent(bad);
  expect(
    screen.getByText(cs5800.body.answer_evidence.catalog.description),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('link', { name: '查看 CS 6140' }),
  ).toBeInTheDocument();
});
it.each([
  [404, '没有找到这门课。'],
  [null, '暂时连不上服务，请稍后重新加载。'],
  [429, '请求过于频繁，请稍后重新加载。'],
  [503, '服务暂时出错，请稍后重新加载。'],
  [418, '加载没有完成，请稍后重新加载。'],
] as const)(
  'error status %s has fixed text and is removable without a view link',
  async (httpStatus, message) => {
    const { input } = page({
      ids: ['failed-id'],
      columns: { 'failed-id': { status: 'error', httpStatus } },
    });
    expect(
      screen.getByText(`课程加载失败（failed-id）：${message}`),
    ).toBeInTheDocument();
    expect(screen.getAllByText('加载失败')).toHaveLength(7);
    expect(
      screen.queryByRole('link', { name: /查看/ }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: '移出 failed-id' }),
    );
    expect(input.onRemove).toHaveBeenCalledExactlyOnceWith('failed-id');
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(input.onReload).toHaveBeenCalledExactlyOnceWith();
  },
);
it.each([
  null,
  [],
  { course_id: 'c2' },
  // Each identity field on its own, so none of the three checks goes unpinned (acceptance).
  { primary_code: 'CS 5800', primary_name: 'Algorithms' },
  { course_id: 'c2', primary_name: 'Algorithms' },
  { course_id: 'c2', primary_code: 'CS 5800' },
  { course_id: 'c2', primary_code: 'CS 5800', primary_name: 7 },
])('unrecognised ready body %j fails the column, not the page', (body) => {
  page({ ids: ['bad'], columns: { bad: { status: 'ready', body } } });
  expect(
    screen.getByText('课程加载失败（bad）：服务返回了无法识别的内容。'),
  ).toBeInTheDocument();
  expect(screen.getAllByText('加载失败')).toHaveLength(7);
  expect(screen.queryByRole('link', { name: /查看/ })).not.toBeInTheDocument();
});
it('missing columns are loading, independently removable and never show reload', () => {
  page({ ids: ['pending'], columns: {} });
  expect(screen.getAllByText('正在加载')).toHaveLength(8);
  expect(
    screen.queryByRole('button', { name: '重新加载' }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '移出 pending' })).toBeEnabled();
});
it('ready has no reload; clear invokes its injected callback without an event argument', async () => {
  const { input } = page();
  expect(
    screen.queryByRole('button', { name: '重新加载' }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '清空对比' }));
  expect(input.onClear).toHaveBeenCalledExactlyOnceWith();
});
it('course-controlled text stays literal and only the validated catalog link becomes external', () => {
  const text =
    '<b data-untrusted="yes">Literal</b> [链接](https://example.com)';
  const body = {
    ...cs5800.body,
    primary_name: text,
    answer_evidence: {
      ...cs5800.body.answer_evidence,
      catalog: { ...cs5800.body.answer_evidence.catalog, description: text },
    },
  };
  const { container } = page({
    ids: [body.course_id],
    columns: { [body.course_id]: { status: 'ready', body } },
  });
  expect(screen.getAllByText(text)).toHaveLength(2);
  expect(container.querySelector('[data-untrusted],script')).toBeNull();
  expect(container.querySelector('a[href="https://example.com"]')).toBeNull();
});
it('header metadata failure is local to the header, not its course cells', () => {
  page({
    ids: [cs5800.body.course_id],
    columns: {
      [cs5800.body.course_id]: {
        status: 'ready',
        body: { ...cs5800.body, credits: 'four' },
      },
    },
  });
  expect(screen.getAllByText(bad)).toHaveLength(1);
  expect(
    screen.getByText(cs5800.body.answer_evidence.catalog.description),
  ).toBeInTheDocument();
});
it('unrelated column updates do not steal focus after a remove', async () => {
  let input = props();
  const { rerender } = page(input);
  await userEvent.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  input = {
    ...input,
    ids: input.ids.filter((id) => id !== cs6140.body.course_id),
  };
  const view = () => (
    <MemoryRouter>
      <ComparePage {...input} />
    </MemoryRouter>
  );
  rerender(view());
  expect(screen.getByRole('button', { name: '移出 DS 5220' })).toHaveFocus();
  screen.getByRole('button', { name: '清空对比' }).focus();
  input = {
    ...input,
    ids: [...input.ids],
    columns: {
      ...input.columns,
      [cs5800.body.course_id]: { status: 'loading' },
    },
  };
  rerender(view());
  expect(screen.getByRole('button', { name: '清空对比' })).toHaveFocus();
});
for (const mode of ['four', 'failed', 'empty'] as const)
  it(`axe compare ${mode} has no violations`, async () => {
    const { container } = page(
      mode === 'empty'
        ? { ids: [] }
        : mode === 'failed'
          ? {
              ids: ['failed'],
              columns: { failed: { status: 'error', httpStatus: 404 } },
            }
          : {},
    );
    expect(
      (
        await axe(container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });
