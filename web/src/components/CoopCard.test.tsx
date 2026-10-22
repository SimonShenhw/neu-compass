import { render as renderView, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Industry } from '../api/coop';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { CoopCard } from './CoopCard';
import { filterCoops } from '../models/coop';
import type { CoopRecord } from '../models/coop';

function render(node: ReactNode) {
  return renderView(<MemoryRouter>{node}</MemoryRouter>);
}

const record: CoopRecord = {
  coop_id: 'test-coop',
  company: '测试公司',
  role: 'Data Co-op',
  industry: null,
  coop_term: null,
  duration_months: null,
  related_courses: ['CS 5800'],
  visibility_level: 0,
  interview_summary: null,
  technical_questions: null,
  salary_range_usd: null,
};

it('student-controlled fields remain literal text, not HTML or Markdown', () => {
  const literal =
    '<b data-untrusted="yes">原文</b> [打开](javascript:alert(1))';
  const { container } = render(
    <CoopCard
      record={{
        ...record,
        related_courses: [],
        company: '<em>测试公司</em>',
        interview_summary: literal,
        technical_questions: '<script>example</script>',
        salary_range_usd: '<strong>salary</strong>',
        visibility_level: 2,
      }}
    />,
  );
  expect(
    screen.getByRole('article', { name: /<em>测试公司<\/em>/ }),
  ).toBeInTheDocument();
  expect(screen.getByText(literal)).toBeInTheDocument();
  expect(screen.getByText('<script>example</script>')).toBeInTheDocument();
  expect(screen.getByText('<strong>salary</strong>')).toBeInTheDocument();
  expect(container.querySelector('a, em, script, [data-untrusted]')).toBeNull();
});
it('missing metadata is omitted without a dangling term separator and courses link locally', () => {
  render(<CoopCard record={record} />);
  expect(screen.queryByText('未提供')).not.toBeInTheDocument();
  expect(screen.getByRole('heading')).toHaveTextContent(
    '测试公司 — Data Co-op',
  );
  expect(screen.getByRole('heading')).not.toHaveTextContent('·');
  expect(screen.getByRole('link', { name: 'CS 5800' })).toHaveAttribute(
    'href',
    '/course/CS-5800',
  );
  expect(screen.getByText('CS 5800')).toBeInTheDocument();
  expect(screen.queryByText(/个月/)).not.toBeInTheDocument();
  expect(screen.queryByText(/这条有/)).not.toBeInTheDocument();
});
it.each(['future_industry', '__proto__', 'constructor'])(
  'unknown industry %s is retained as plain text rather than discarded',
  (industry) => {
    render(<CoopCard record={{ ...record, industry: industry as Industry }} />);
    expect(screen.getByText(industry)).toBeInTheDocument();
  },
);
it('technical-only details do not invent an interview-summary or a lock hint', async () => {
  render(
    <CoopCard
      record={{
        ...record,
        visibility_level: 1,
        technical_questions: '技术问题合成原文',
      }}
    />,
  );
  expect(screen.queryByText('面试经过')).not.toBeInTheDocument();
  expect(screen.queryByText(/这条有面试细节/)).not.toBeInTheDocument();
  expect(screen.getByText('技术问题合成原文')).not.toBeVisible();
  await userEvent.click(screen.getByText('技术问题'));
  expect(screen.getByText('技术问题合成原文')).toBeVisible();
});
it('filters preserve order and never mutate the supplied response', () => {
  const rows: CoopRecord[] = [
    record,
    { ...record, coop_id: 'second', company: '另一家', industry: 'big_tech' },
  ];
  const before = structuredClone(rows);
  expect(filterCoops(rows, '  DATA  ', 'all')).toEqual(rows);
  expect(filterCoops(rows, '', 'missing')).toEqual([record]);
  expect(filterCoops(rows, '', 'big_tech').map((row) => row.coop_id)).toEqual([
    'second',
  ]);
  expect(rows).toEqual(before);
});
