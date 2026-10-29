import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { CourseDetail } from './CourseDetail';
import {
  detailData,
  expandDetail,
  readDetail,
  setDetail,
} from './detailTestUtils';
import {
  addToCompare,
  getCompareList,
  MAX_COMPARE_COURSES,
} from '../../models/compareList';
import { requisitesFixture } from '../../fixtures/requisitesDemo';

function input() {
  return {
    course: detailData(),
    compare: [] as string[],
    onAddToCompare: vi.fn(),
    onOpenCourse: vi.fn(),
  };
}
it.each([
  { name: 'empty', ids: [], disabled: false, note: null },
  {
    name: 'already',
    ids: ['other', 'c-cs-6140'],
    disabled: true,
    note: '已在对比中（2/4）',
  },
  {
    name: 'full',
    ids: ['a', 'b', 'c', 'd'],
    disabled: true,
    note: '对比列表已满，请到课程对比页先移出一门。',
  },
  {
    name: 'full already',
    ids: ['a', 'b', 'c', 'c-cs-6140'],
    disabled: true,
    note: '已在对比中（4/4）',
  },
])(
  'compare $name uses already-first precedence and the exact callback ID',
  async ({ ids, disabled, note }) => {
    const props = input();
    render(<CourseDetail {...props} compare={ids} />);
    const button = screen.getByRole('button', {
      name: '加入对比',
    });
    expect((button as HTMLButtonElement).disabled).toBe(disabled);
    if (note) expect(screen.getByText(note)).toBeVisible();
    if ((ids as readonly string[]).includes('c-cs-6140'))
      expect(
        screen.queryByText('对比列表已满，请到课程对比页先移出一门。'),
      ).not.toBeInTheDocument();
    await userEvent.setup().click(button);
    if (disabled) expect(props.onAddToCompare).not.toHaveBeenCalled();
    else
      expect(props.onAddToCompare).toHaveBeenCalledExactlyOnceWith('c-cs-6140');
  },
);
it('four-course limit is shared with the R5b store without changing store behavior', () => {
  expect(MAX_COMPARE_COURSES).toBe(4);
  for (const id of ['a', 'b', 'c', 'd']) expect(addToCompare(id)).toBe('added');
  expect(addToCompare('e')).toBe('full');
  expect(getCompareList()).toEqual(['a', 'b', 'c', 'd']);
});
it('zero credits and zero workload are shown, absent or empty chips are not invented', () => {
  const props = input();
  const data = detailData();
  data.credits = 0;
  data.workload_hours_per_week = 0;
  data.term = '';
  data.delivery_mode = null;
  const { container, rerender } = render(
    <CourseDetail {...props} course={data} />,
  );
  expect(readDetail(container).find((e) => e.kind === 'header')?.chips).toEqual(
    [{ label: 'Credits', value: '0' }],
  );
  expect(screen.getByText('每周约 0 小时 · 难度 4/5')).toBeVisible();
  data.credits = null;
  rerender(<CourseDetail {...props} course={data} />);
  expect(container.querySelector('[data-chip]')).toBeNull();
});
it('the chip row is not drawn once no chip is left', () => {
  const props = input();
  const data = detailData();
  data.term = '';
  data.delivery_mode = null;
  const { container, rerender } = render(
    <CourseDetail {...props} course={data} />,
  );
  const header = () => container.querySelector('[data-kind="header"]')!;
  expect(header().children).toHaveLength(3);
  data.credits = null;
  rerender(<CourseDetail {...props} course={data} />);
  expect(header().children).toHaveLength(2);
});
it('the header course code is folded onto one line like the name', () => {
  const data = detailData();
  data.primary_code = 'CS\f6140\n';
  const { container } = render(<CourseDetail {...input()} course={data} />);
  expect(readDetail(container).find((e) => e.kind === 'header')?.code).toBe(
    'CS 6140',
  );
});
it('signed-zero estimates, grading and confidence preserve Python display through the real page', async () => {
  const data = detailData();
  data.workload_hours_per_week = -0;
  data.grading_components = [{ name: 'Signed zero', weight: -0 }];
  setDetail(data, 'evidence_snippets.0.confidence', -0);
  const { container } = render(<CourseDetail {...input()} course={data} />);
  await expandDetail(container);
  const events = readDetail(container);
  expect(events.find((e) => e.label === '学生评价里的估计')?.value).toBe(
    '每周约 -0 小时 · 难度 4/5',
  );
  expect(events.find((e) => e.label === '考核构成')?.value).toBe(
    'Signed zero -0%',
  );
  expect(
    events.some(
      (e) => e.text === '每周工作量 · 抽取置信度 -0.00（不是事实概率）',
    ),
  ).toBe(true);
});
it('single-line fields use Python splitlines while labelled values and AI notes only drop CR', async () => {
  const data = detailData();
  data.primary_name = 'A\n\nB\n';
  data.term = 'Fall\r\n2026\n';
  data.topics_covered = ['X\vY\n'];
  data.skill_tags = ['X\u2028Y\n'];
  setDetail(data, 'program_context.0.program_name', 'P\x85Q\n');
  data.professor = ['A\r\nB'];
  data.career_relevance = ['C\rD'];
  setDetail(data, 'ai_policy.notes', 'E\r\nF\rG');
  const { container } = render(<CourseDetail {...input()} course={data} />);
  await expandDetail(container);
  const events = readDetail(container);
  expect(events.find((e) => e.kind === 'header')).toMatchObject({
    name: 'A  B',
    chips: expect.arrayContaining([{ label: 'Term', value: 'Fall 2026' }]),
  });
  expect(events.filter((e) => e.kind === 'pills').map((e) => e.items)).toEqual([
    ['X Y'],
    ['X Y'],
  ]);
  expect(events.find((e) => e.kind === 'program_row')?.name).toBe('P Q');
  expect(events.find((e) => e.label === '任课老师')?.value).toBe('A\nB');
  expect(events.find((e) => e.label === '职业方向')?.value).toBe('CD');
  expect(events.some((e) => e.text === 'E\nFG')).toBe(true);
});
it('all topics and skills remain visible beyond eight, preserving duplicates and unknown placement fallback', () => {
  const data = detailData();
  data.topics_covered = Array.from({ length: 10 }, (_, n) => `Topic ${n}`);
  data.skill_tags = ['same', 'same'];
  setDetail(data, 'program_context.0.requirement_type', 'constructor');
  setDetail(data, 'program_context.1.requirement_type', 'capstone');
  const { container } = render(<CourseDetail {...input()} course={data} />);
  const events = readDetail(container);
  expect(events.filter((e) => e.kind === 'pills').map((e) => e.items)).toEqual([
    data.topics_covered,
    ['same', 'same'],
  ]);
  expect(
    events.filter((e) => e.kind === 'program_row').map((e) => e.badge),
  ).toEqual(['基础 · foundation', '毕业项目 · capstone']);
});
it('malformed snapshot ID keeps valid description and official links but never gets a full-ID tooltip', async () => {
  const { container } = render(
    <CourseDetail
      {...input()}
      course={detailData('derived-malformed-snapshot-id')}
    />,
  );
  await expandDetail(container);
  expect(screen.getByText(/快照：格式异常 · 导入：/)).not.toHaveAttribute(
    'title',
  );
  expect(container.querySelectorAll('a')).toHaveLength(2);
  expect(
    screen.getByText(/Covers supervised learning, model selection/),
  ).toBeVisible();
});
it('untrusted fields remain literal in every display context and only vetted anchors are created', async () => {
  const text = '<b>x</b> [链接](https://example.com) javascript:alert(1)';
  const data = detailData();
  data.primary_name = text;
  data.professor = [text];
  data.topics_covered = [text];
  data.skill_tags = [text];
  data.career_relevance = [text];
  for (const path of [
    'answer_evidence.catalog.description',
    'grading_components.0.name',
    'program_context.0.program_name',
    'ai_policy.notes',
    'evidence_snippets.0.quote',
    'evidence_snippets.0.source_id',
    'evidence_snippets.0.field',
  ])
    setDetail(data, path, text);
  setDetail(data, 'answer_evidence.source_review_ids', [text]);
  setDetail(data, 'answer_evidence.warnings', [text]);
  setDetail(data, 'answer_evidence.missing_fields', [text]);
  const { container } = render(<CourseDetail {...input()} course={data} />);
  await expandDetail(container);
  const events = readDetail(container);
  expect(events.find((e) => e.kind === 'header')?.name).toBe(text);
  expect(events.find((e) => e.label === '考核构成')?.value).toContain(
    `${text} 30%`,
  );
  expect(events.find((e) => e.label === '任课老师')?.value).toBe(text);
  expect(events.find((e) => e.kind === 'program_row')?.name).toBe(text);
  expect(events.filter((e) => e.kind === 'pills').map((e) => e.items)).toEqual([
    [text],
    [text],
  ]);
  expect(
    events.filter((e) => e.kind === 'text' && e.text === text),
  ).toHaveLength(3);
  expect(
    events.some((e) => e.text === `缺失：${text}；缺失不等于零/简单/无要求。`),
  ).toBe(true);
  expect(events.some((e) => e.kind === 'note' && e.text === text)).toBe(true);
  expect(
    events.some((e) =>
      e.text?.includes(`来源：其他来源 · ${text}\n引文：${text}`),
    ),
  ).toBe(true);
  expect(container.querySelectorAll('b, script, img')).toHaveLength(0);
  const links = [...container.querySelectorAll('a')];
  expect(links).toHaveLength(2);
  for (const link of links) {
    expect(link).toHaveAttribute(
      'href',
      'https://catalog.northeastern.edu/course-descriptions/cs/',
    );
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
});
it('independent malformed fields suppress only their UI blocks, not unrelated valid content', async () => {
  const data = detailData();
  data.grading_components = [
    { name: 'ok', weight: 0.3 },
    { name: '', weight: null },
  ];
  data.professor = [1];
  data.ai_policy = {
    permitted_tools: [],
    banned_tools: [],
    disclosure_required: true,
    notes: 1,
  };
  data.topics_covered = [null];
  data.credits = 99;
  const { container } = render(<CourseDetail {...input()} course={data} />);
  await expandDetail(container);
  const events = readDetail(container);
  expect(
    events.some(
      (e) =>
        e.label === '考核构成' ||
        e.label === '任课老师' ||
        e.text === 'AI 使用政策' ||
        e.text === '主题',
    ),
  ).toBe(false);
  expect(
    events
      .find((e) => e.kind === 'header')
      ?.chips?.some((chip) => chip.label === 'Credits'),
  ).toBe(false);
  expect(screen.getByText('技能')).toBeVisible();
  expect(screen.getByText(/Covers supervised learning/)).toBeVisible();
  expect(screen.getByRole('button', { name: '加入对比' })).toBeEnabled();
});
it('old or malformed answer evidence does not suppress independent root snippets; provenance stays available', async () => {
  const data = detailData();
  data.answer_evidence = { warnings: [1] };
  const { container } = render(<CourseDetail {...input()} course={data} />);
  await expandDetail(container);
  expect(screen.getByText('评价和大纲原文摘录（4 条）')).toBeVisible();
  expect(
    screen.queryByText('来源：未附可追溯目录快照'),
  ).not.toBeInTheDocument();
  expect(container.querySelectorAll('a')).toHaveLength(0);
});
it('R3a callbacks are passed through and course keys reset its annual selection with valid controls', async () => {
  const rules = requisitesFixture('cs-6140-two-years').body;
  const props = input();
  const data = {
    ...detailData(),
    course_requisites: structuredClone(rules.course_requisites),
    prerequisites: rules.prerequisites,
  };
  const { rerender } = render(<CourseDetail {...props} course={data} />);
  const user = userEvent.setup();
  async function chooseYear() {
    await user.click(
      screen.getByRole('combobox', { name: /^先修规则的 Catalog/ }),
    );
    await user.click(
      screen.getByRole('option', {
        name: 'Catalog 2026-2027（校区和个人路径未声明）',
      }),
    );
  }
  await chooseYear();
  await user.click(screen.getByRole('button', { name: '查看 DS 5220' }));
  expect(props.onOpenCourse).toHaveBeenLastCalledWith('DS 5220');
  // The legacy rows' buttons, named for their courses as the rule tree's are (R6).
  await user.click(
    screen
      .getAllByRole('button', { name: /^查看 / })
      .find((button) => button.dataset.part === 'legacy')!,
  );
  expect(props.onOpenCourse).toHaveBeenLastCalledWith('CS 5100');
  const next = structuredClone(data);
  next.course_id = 'c-cs-6150';
  next.primary_code = 'CS 6150';
  next.primary_name = 'Another synthetic course';
  const listing = next.course_requisites as {
    documents: {
      course_id: string;
      course_code: string;
      course_name: string;
    }[];
    program_contexts: { course_code: string }[];
  };
  for (const doc of listing.documents) {
    doc.course_id = next.course_id;
    doc.course_code = next.primary_code;
    doc.course_name = next.primary_name;
  }
  for (const context of listing.program_contexts)
    context.course_code = next.primary_code;
  rerender(<CourseDetail {...props} course={next} />);
  expect(
    screen.getByRole('combobox', { name: /^先修规则的 Catalog/ }),
  ).toHaveTextContent('请选择适用的年份');
  await chooseYear();
  expect(screen.getByRole('button', { name: '查看 DS 5220' })).toBeVisible();
});
it('AI disclosure and all provenance start folded and remain keyboard reachable', async () => {
  const { container } = render(<CourseDetail {...input()} />);
  const details = [...container.querySelectorAll('details')];
  expect(details).toHaveLength(3);
  expect(details.every((d) => !d.open)).toBe(true);
  const user = userEvent.setup();
  await user.tab();
  expect(screen.getByRole('button', { name: '加入对比' })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('link', { name: 'NEU 官方课程目录' })).toHaveFocus();
  await user.tab();
  expect(document.activeElement?.tagName).toBe('SUMMARY');
  // jsdom has no native summary Enter default action; real-browser QA covers activation.
});
it.each([
  'cs-6140-everything',
  'cs-5800-identity-only',
  'derived-foreign-catalog-link',
  'invalid',
])('detail axe has no violations for %s', async (caseName) => {
  const { container } = render(
    <CourseDetail
      {...input()}
      course={caseName === 'invalid' ? {} : detailData(caseName)}
    />,
  );
  await expandDetail(container);
  expect(
    (await axe(container, { rules: { 'color-contrast': { enabled: false } } }))
      .violations,
  ).toEqual([]);
});
