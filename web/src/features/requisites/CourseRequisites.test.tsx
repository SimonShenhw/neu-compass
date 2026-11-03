import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import type { CourseRequisitesProps } from './CourseRequisites';
import { CourseRequisites, YEAR_EMPTY, YEAR_LABEL } from './CourseRequisites';
import { PLAN_EMPTY, PLAN_LABEL } from './ProgramContextPanel';
import { requisitesFixture } from '../../fixtures/requisitesDemo';
import { catalogPrereqCodes, evidence } from '../../models/courseDetail';
import { planLabel } from '../../models/requisiteRules';
import {
  choose,
  edit,
  expandAll,
  listing,
  twoYears,
} from './requisitesTestUtils';

function props(caseName = twoYears.case): CourseRequisitesProps {
  const fixture = requisitesFixture(caseName);
  // requisitesFixture falls back to the default case for an unknown name.
  if (fixture.case !== caseName) throw Error(`No fixture ${caseName}`);
  return {
    course: fixture.body,
    requisites: fixture.body.course_requisites,
    prerequisites: fixture.body.prerequisites,
    catalogPrereqCodes: catalogPrereqCodes(
      evidence(fixture.body.answer_evidence),
    ),
    onOpenCourse: vi.fn(),
  };
}
const year = (value: string) => `Catalog ${value}（校区和个人路径未声明）`;
const selectedPlan = () => planLabel(listing().program_contexts[0]!.plans[0]!);
async function programDisclosure() {
  await userEvent
    .setup()
    .click(screen.getByText('同一年份培养方案里的相关要求'));
}
// The legacy rows' 查看 buttons: named for their courses, as the rule tree's are (R6).
const legacyButtons = () =>
  screen
    .getAllByRole('button', { name: /^查看 / })
    .filter((button) => button.dataset.part === 'legacy');
it('multiple years start empty; a single year starts selected but clearing survives rerenders', async () => {
  const input = props();
  const { rerender } = render(<CourseRequisites {...input} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(YEAR_EMPTY);
  expect(
    screen.queryByRole('heading', { name: '先修课' }),
  ).not.toBeInTheDocument();
  const single = props('cs-5008-one-year-repeated-leaf');
  rerender(<CourseRequisites {...single} key={single.course.course_id} />);
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(YEAR_LABEL),
    }),
  ).toHaveTextContent('2026-2027');
  await choose(YEAR_LABEL, YEAR_EMPTY);
  rerender(<CourseRequisites {...single} key={single.course.course_id} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(YEAR_EMPTY);
  expect(
    screen.queryByRole('heading', { name: '先修课' }),
  ).not.toBeInTheDocument();
  rerender(
    <CourseRequisites
      {...props('cs-5800-nothing-listed')}
      key="another-course"
    />,
  );
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(YEAR_LABEL),
    }),
  ).toHaveTextContent('2026-2027');
});
it('changing years clears plan selection including returning to the original year', async () => {
  const data = listing();
  // IDs are unique within a context, not across years. This must reset even when
  // the selected ID still exists; relying on the removed-ID guard is insufficient.
  const older = structuredClone(data.program_contexts[0]!.plans[0]!);
  older.catalog_year = '2025-2026';
  older.source_catalog_year = '2025-2026';
  older.source_url =
    'https://catalog.northeastern.edu/archive/2025-2026/graduate/synthetic-program/';
  data.program_contexts[1]!.plans = [older];
  render(<CourseRequisites {...props()} requisites={data} />);
  await choose(YEAR_LABEL, year('2026-2027'));
  await programDisclosure();
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(PLAN_LABEL),
    }),
  ).toHaveTextContent(PLAN_EMPTY);
  await choose(PLAN_LABEL, selectedPlan());
  await choose(YEAR_LABEL, year('2025-2026'));
  await programDisclosure();
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(PLAN_LABEL),
    }),
  ).toHaveTextContent(PLAN_EMPTY);
  await choose(YEAR_LABEL, year('2026-2027'));
  await programDisclosure();
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(PLAN_LABEL),
    }),
  ).toHaveTextContent(PLAN_EMPTY);
  expect(
    screen.queryByText('partial · 来源片段已对照'),
  ).not.toBeInTheDocument();
});
it('removed year and plan choices do not resurrect when data returns', async () => {
  const input = props();
  const { rerender } = render(<CourseRequisites {...input} />);
  await choose(YEAR_LABEL, year('2026-2027'));
  await programDisclosure();
  await choose(PLAN_LABEL, selectedPlan());
  const noPlan = listing();
  noPlan.program_contexts[0]!.plans.shift();
  rerender(<CourseRequisites {...input} requisites={noPlan} />);
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(PLAN_LABEL),
    }),
  ).toHaveTextContent(PLAN_EMPTY);
  rerender(<CourseRequisites {...input} />);
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(PLAN_LABEL),
    }),
  ).toHaveTextContent(PLAN_EMPTY);
  const noYear = listing();
  noYear.documents.shift();
  noYear.program_contexts.shift();
  rerender(<CourseRequisites {...input} requisites={noYear} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(YEAR_EMPTY);
  rerender(<CourseRequisites {...input} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(YEAR_EMPTY);
});
it('tree nesting and exact callbacks include grade level and concurrent suffixes', async () => {
  const input = props();
  const { container } = render(<CourseRequisites {...input} />);
  await choose(YEAR_LABEL, year('2026-2027'));
  const trees = container.querySelectorAll('[data-rule-tree]');
  expect(trees).toHaveLength(2);
  expect(
    [...trees[0]!.querySelectorAll('[data-tree-depth]')].map((li) =>
      Number(li.getAttribute('data-tree-depth')),
    ),
  ).toEqual([0, 1, 2, 2, 1, 2, 2]);
  const user = userEvent.setup();
  const buttons = within(trees[0] as HTMLElement).getAllByRole('button');
  expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
    '查看 CS 5800',
    '查看 CS 7800',
    '查看 DS 5220',
    '查看 CS 6220',
  ]);
  expect(buttons[2]!.parentElement).toHaveTextContent(
    'DS 5220（最低成绩：C-；原文 level 标记：Graduate（不自动判断适用学生））',
  );
  expect(buttons[3]!.parentElement).toHaveTextContent(
    'CS 6220（原文明示可并修；仍需核实其余条件）',
  );
  for (const button of buttons) await user.click(button);
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(1, 'CS 5800');
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(2, 'CS 7800');
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(3, 'DS 5220');
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(4, 'CS 6220');
  expect(input.onOpenCourse).toHaveBeenCalledTimes(4);
});
it('legacy labels remain only for genuinely absent structured records, including missing schema', () => {
  const input = {
    ...props('cs-6140-requisites-table-missing'),
    catalogPrereqCodes: ['CS 5800', 'CS 7800'],
  };
  const { container, rerender } = render(<CourseRequisites {...input} />);
  expect(screen.getByText('目录列出')).toBeVisible();
  expect(screen.getByText('目录未列出')).toBeVisible();
  expect(legacyButtons()).toHaveLength(2);
  const labels = () => container.querySelectorAll('[data-row-label]');
  const data = listing('cs-6140-requisites-table-missing');
  data.unusable_records = 1;
  rerender(<CourseRequisites {...input} requisites={data} />);
  expect(labels()).toHaveLength(0);
  data.unusable_records = 0;
  data.warnings.push('structured_requisite_schema_unusable');
  rerender(<CourseRequisites {...input} requisites={data} />);
  expect(labels()).toHaveLength(0);
  data.warnings = [];
  data.has_any_stored_records = true;
  rerender(<CourseRequisites {...input} requisites={data} />);
  expect(labels()).toHaveLength(0);
  expect(screen.queryByText(/「目录列出」/)).not.toBeInTheDocument();
});
const LEGACY_NOTE =
  '旧边不表达 AND/OR、最低成绩或共修；不能用它判断哪些课全部必修或能否注册。';
const LISTING_NOTE =
  '「目录列出」：本课记录的目录先修段提到了这门课，关系仍未核验；「目录未列出」：目录先修段没有提到。';
it('a legacy row says only whether the course’s catalog entry lists its code; the note explains that only when a row says it', () => {
  const rows = [
    {
      course_id: 'listed',
      primary_code: 'cs  5800',
      primary_name: 'Algorithms',
      requirement: 'recommended',
    },
    {
      course_id: 'unlisted',
      primary_code: 'CS 5100',
      primary_name: 'Foundations of Artificial Intelligence',
      requirement: 'required',
    },
    {
      course_id: 'no-code',
      primary_code: null,
      primary_name: 'Name without code',
      requirement: 'required',
    },
  ];
  const input = { ...props(), requisites: undefined, prerequisites: rows };
  const { container, rerender } = render(
    <CourseRequisites {...input} catalogPrereqCodes={['CS 5800', 'CS 7800']} />,
  );
  const shown = () =>
    [...container.querySelectorAll('[data-kind="legacy_row"]')].map(
      (row) => row.querySelector('[data-row-label]')?.textContent ?? null,
    );
  expect(shown()).toEqual(['目录列出', '目录未列出', null]);
  expect(screen.getByText(LEGACY_NOTE + LISTING_NOTE)).toBeVisible();
  rerender(<CourseRequisites {...input} catalogPrereqCodes={[]} />);
  expect(shown()).toEqual(['目录未列出', '目录未列出', null]);
  expect(screen.getByText(LEGACY_NOTE + LISTING_NOTE)).toBeVisible();
  // No catalog snapshot, or no row with a code: no labels, and the note says nothing about them.
  rerender(<CourseRequisites {...input} catalogPrereqCodes={null} />);
  expect(shown()).toEqual([null, null, null]);
  expect(screen.getByText(LEGACY_NOTE)).toBeVisible();
  rerender(
    <CourseRequisites
      {...input}
      prerequisites={[rows[2]]}
      catalogPrereqCodes={['CS 5800']}
    />,
  );
  expect(shown()).toEqual([null]);
  expect(screen.getByText(LEGACY_NOTE)).toBeVisible();
  // Next to structured rules the rows stay plain links, whatever the catalog lists.
  rerender(
    <CourseRequisites
      {...input}
      requisites={listing()}
      catalogPrereqCodes={['CS 5800', 'CS 5100']}
    />,
  );
  expect(shown()).toEqual([null, null, null]);
  expect(screen.queryByText(/「目录列出」/)).not.toBeInTheDocument();
  for (const tier of [
    '必须先修',
    '建议先修',
    '可同修',
    'required',
    'recommended',
  ])
    expect(screen.queryByText(tier)).not.toBeInTheDocument();
});
it('no requirement tier is shown, known or not; missing course has no View; each callback is exact', async () => {
  const input = props();
  const rows = [
    {
      course_id: 'id-only',
      primary_code: null,
      primary_name: 'Name without code',
      requirement: 'constructor',
    },
    {
      course_id: 'code-only',
      primary_code: 'CS 1',
      primary_name: null,
      requirement: 'other',
    },
    {
      course_id: 'both',
      primary_code: 'CS 2',
      primary_name: 'Name',
      requirement: 'concurrent',
    },
  ];
  const { container, rerender } = render(
    <CourseRequisites {...input} requisites={undefined} prerequisites={rows} />,
  );
  for (const tier of ['constructor', 'other', 'concurrent', '可同修'])
    expect(screen.queryByText(tier)).not.toBeInTheDocument();
  expect(container.querySelectorAll('[data-row-label]')).toHaveLength(0);
  expect(container.querySelectorAll('[data-row-id]')).toHaveLength(2);
  const user = userEvent.setup();
  // Each says which course it opens, not only 「查看」: a row without a code has none.
  expect(legacyButtons()).toEqual([
    screen.getByRole('button', { name: '查看 CS 1' }),
    screen.getByRole('button', { name: '查看 CS 2' }),
  ]);
  for (const button of legacyButtons()) await user.click(button);
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(1, 'CS 1');
  expect(input.onOpenCourse).toHaveBeenNthCalledWith(2, 'CS 2');
  rerender(
    <CourseRequisites {...input} requisites={{}} prerequisites={rows} />,
  );
  expect(container.querySelectorAll('[data-row-label]')).toHaveLength(0);
  expect(screen.getByText('Name without code')).toBeVisible();
  expect(screen.getByText('CS 1')).toBeVisible();
});
it('a legacy row’s 查看 says a code with a line break on one line, and opens the code as it came (R6)', async () => {
  const input = props();
  const rows = [
    {
      course_id: 'broken',
      primary_code: 'CS\n5800',
      primary_name: null,
      requirement: 'other',
    },
  ];
  render(
    <CourseRequisites {...input} requisites={undefined} prerequisites={rows} />,
  );
  expect(legacyButtons()).toEqual([
    screen.getByRole('button', { name: '查看 CS 5800' }),
  ]);
  await userEvent.setup().click(legacyButtons()[0]!);
  expect(input.onOpenCourse).toHaveBeenCalledWith('CS\n5800');
});
it.each([
  [],
  null,
  {},
  [null],
  [{ course_id: 1 }],
  [{ course_id: 'x', primary_code: null, primary_name: null, requirement: 1 }],
])('malformed or empty legacy list %j is entirely hidden', (prerequisites) => {
  const { container } = render(
    <CourseRequisites {...props()} prerequisites={prerequisites} />,
  );
  expect(container.querySelector('[data-part="legacy"]')).toBeNull();
});
it('warning flags alone are sufficient and identity checks include ID code and name', async () => {
  const input = props();
  const data = listing();
  data.warnings.push('structured_requisite_schema_unusable');
  data.program_contexts[0]!.unusable_records = 0;
  data.program_contexts[0]!.warnings.push('program_context_schema_unusable');
  const { rerender } = render(
    <CourseRequisites {...input} requisites={data} />,
  );
  expect(screen.getByText(/存在无法使用的结构化记录或存储结构/)).toBeVisible();
  await choose(YEAR_LABEL, year('2026-2027'));
  await programDisclosure();
  expect(
    screen.getByText(/存在同年度无法使用的方案记录或存储结构/),
  ).toBeVisible();
  for (const field of ['course_id', 'course_code', 'course_name']) {
    const bad = listing();
    edit(bad, `documents.0.${field}`, 'different');
    if (field === 'course_code') {
      bad.documents[0]!.source.url =
        'https://catalog.northeastern.edu/course-descriptions/different/';
      bad.program_contexts[0]!.course_code = 'different';
    }
    rerender(<CourseRequisites {...input} requisites={bad} />);
    expect(
      screen.getByText('一份结构化记录的课程身份不符，未显示。'),
    ).toBeVisible();
    expect(
      screen.queryByRole('option', { name: /2026-2027/ }),
    ).not.toBeInTheDocument();
  }
});
it('all untrusted text is literal and only two vetted source anchors are rendered', async () => {
  const text = '<b>x</b> [链接](https://example.com) javascript:alert(1)';
  const input = props();
  const data = listing();
  edit(data, 'documents.0.requisites.prerequisite', {
    status: 'unparsed',
    raw_text: text,
    reason: text,
    rule: null,
  });
  edit(data, 'documents.0.description_evidence.paragraphs.0', text);
  edit(data, 'program_contexts.0.plans.0.notes', text);
  edit(data, 'program_contexts.0.plans.0.requirements.label', text);
  edit(data, 'program_contexts.0.plans.0.source_excerpt', text);
  const { container } = render(
    <CourseRequisites {...input} requisites={data} />,
  );
  await choose(YEAR_LABEL, year('2026-2027'));
  await expandAll(container);
  await choose(PLAN_LABEL, selectedPlan());
  await expandAll(container);
  expect(container.querySelector('b')).toBeNull();
  expect(screen.getAllByText(text)).toHaveLength(4);
  expect(
    screen.getByText(`未解析：${text}；保留整段，不展示部分成功树。`),
  ).toBeVisible();
  const links = screen.getAllByRole('link');
  expect(links).toHaveLength(2);
  expect(links.map((a) => a.getAttribute('href'))).toEqual([
    data.documents[0]!.source.url,
    data.program_contexts[0]!.plans[0]!.source_url,
  ]);
  for (const link of links) {
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
});
it('a plan without an HTML digest shows no digest line', async () => {
  const data = listing();
  data.program_contexts[0]!.plans[0]!.source_html_sha256 = null;
  const { container } = render(
    <CourseRequisites {...props()} requisites={data} />,
  );
  await choose(YEAR_LABEL, year('2026-2027'));
  await programDisclosure();
  await choose(PLAN_LABEL, selectedPlan());
  await expandAll(container);
  expect(screen.getByText('partial · 来源片段已对照')).toBeVisible();
  expect(
    screen.queryByText((text) => text.startsWith('培养方案 HTML 字节摘要：')),
  ).not.toBeInTheDocument();
});
it('timestamps replace only a terminal Z and preserve every other byte', async () => {
  const data = listing();
  data.documents[0]!.source.captured_at = 'Z-middle+03:00';
  data.documents[0]!.imported_at = 'precise.123456Z';
  const { container } = render(
    <CourseRequisites {...props()} requisites={data} />,
  );
  await choose(YEAR_LABEL, year('2026-2027'));
  await expandAll(container);
  expect(
    screen.getByText(
      '来源捕获 UTC Z-middle+03:00 · 导入 UTC precise.123456+00:00；不是实时查询',
    ),
  ).toBeVisible();
});
it('keyboard reaches selects disclosures rule leaves and legacy View', async () => {
  const input = props();
  render(<CourseRequisites {...input} />);
  const user = userEvent.setup();
  await user.tab();
  expect(screen.getByRole('combobox')).toHaveFocus();
  await user.keyboard('{Enter}{ArrowDown}{Enter}');
  // The rule tree's leaf; the legacy row for the same course has the same name, as it opens the same page (R6).
  const leaf = () =>
    screen
      .getAllByRole('button', { name: '查看 CS 5800' })
      .find((button) => button.dataset.part !== 'legacy')!;
  expect(leaf()).toBeVisible();
  await user.tab();
  expect(leaf()).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(input.onOpenCourse).toHaveBeenLastCalledWith('CS 5800');
  let disclosure = false;
  let plan = false;
  let view = false;
  for (let i = 0; i < 22; i++) {
    await user.tab();
    const active = document.activeElement as HTMLElement;
    // jsdom does not implement summary's native Enter default action; browser QA covers that action.
    if (active.tagName === 'SUMMARY') {
      disclosure = true;
      if (!active.parentElement!.hasAttribute('open')) await user.click(active);
      expect(active.parentElement).toHaveAttribute('open');
    }
    if (
      active.getAttribute('role') === 'combobox' &&
      active.textContent?.includes(PLAN_LABEL)
    )
      plan = true;
    if (active.textContent === '查看') {
      view = true;
      await user.keyboard(' ');
    }
  }
  expect(disclosure).toBe(true);
  expect(plan).toBe(true);
  expect(view).toBe(true);
});
it.each(['unselected', 'selected', 'legacy', 'legacy listed', 'invalid'])(
  'axe has no violations for %s',
  async (state) => {
    const input = props(
      state === 'legacy'
        ? 'cs-7800-legacy-edges-only'
        : state === 'legacy listed'
          ? 'cs-6140-legacy-catalog-listing'
          : state === 'invalid'
            ? 'derived-invalid-tree'
            : twoYears.case,
    );
    const { container } = render(<CourseRequisites {...input} />);
    if (state === 'selected') {
      await choose(YEAR_LABEL, year('2026-2027'));
      await programDisclosure();
      await choose(PLAN_LABEL, selectedPlan());
      await expandAll(container);
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
