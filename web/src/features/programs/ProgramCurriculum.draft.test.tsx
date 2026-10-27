import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ProgramCurriculum } from './ProgramCurriculum';
import { curriculumProps } from './programTestUtils';

// R4b's one change to R4a: an optional draft slot after the selected plan's block (R4a spec 6.9).
const slot = <div data-testid="draft-slot">草案</div>;
const OLD_TABLE_NOTE =
  '以下是旧课程表的课程分类与学期建议，未经官方核验；校区/年度/路径未知。';

it('the draft shows as given right after the selected plan block and before the old table note', () => {
  render(<ProgramCurriculum {...curriculumProps()} draft={slot} />);
  const draft = screen.getByTestId('draft-slot');
  expect(
    screen.getByRole('region', { name: '已选方案的版本化规则' })
      .nextElementSibling,
  ).toBe(draft);
  expect(draft.nextElementSibling).toHaveTextContent(OLD_TABLE_NOTE);
  expect(screen.getAllByTestId('draft-slot')).toHaveLength(1);
});

it('without a draft the curriculum renders the same elements as with an empty one', () => {
  const tags = (root: HTMLElement) =>
    [...root.querySelectorAll('*')].map((e) => e.tagName);
  const { container: without } = render(
    <ProgramCurriculum {...curriculumProps()} />,
  );
  const { container: empty } = render(
    <ProgramCurriculum {...curriculumProps()} draft={undefined} />,
  );
  expect(tags(empty)).toEqual(tags(without));
  for (const region of screen.getAllByRole('region', {
    name: '已选方案的版本化规则',
  }))
    expect(region.nextElementSibling).toHaveTextContent(OLD_TABLE_NOTE);
});

it.each([
  ['no plan is selected', null],
  ['the selected plan is not in the list', 'cs-ms-boston-2030-2031-standard'],
])('nothing of the draft shows when %s', (_, selectedPlanId) => {
  render(
    <ProgramCurriculum
      {...curriculumProps()}
      selectedPlanId={selectedPlanId}
      draft={slot}
    />,
  );
  expect(screen.queryByTestId('draft-slot')).toBeNull();
});

it.each([
  ['loading', { status: 'loading' } as const],
  [
    'failed',
    {
      status: 'failed',
      failure: {
        status: 503,
        errorType: null,
        retryAfter: null,
        invalidFields: [],
        reason: null,
      },
    } as const,
  ],
  ['unreadable', { status: 'ready', data: { plans: 'x' } } as const],
])('nothing of the draft shows while the curriculum is %s', (_, curriculum) => {
  render(
    <ProgramCurriculum
      {...curriculumProps()}
      curriculum={curriculum}
      draft={slot}
    />,
  );
  expect(screen.queryByTestId('draft-slot')).toBeNull();
});

it('choosing another plan keeps the same draft element, so text typed into it stays', () => {
  const props = curriculumProps();
  const draft = (
    <label>
      课号
      <textarea />
    </label>
  );
  const { rerender } = render(<ProgramCurriculum {...props} draft={draft} />);
  const box = screen.getByLabelText('课号');
  fireEvent.change(box, { target: { value: 'CS 5010' } });
  rerender(
    <ProgramCurriculum
      {...props}
      selectedPlanId="cs-ms-boston-2026-2027-align"
      draft={draft}
    />,
  );
  expect(
    screen.getByRole('heading', { level: 2, name: /Align/ }),
  ).toBeVisible();
  expect(screen.getByLabelText('课号')).toBe(box);
  expect(box).toHaveValue('CS 5010');
});
