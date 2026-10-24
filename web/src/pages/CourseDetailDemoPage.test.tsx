import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../App';
import * as detailDemo from '../fixtures/courseDetailDemo';
import { getCompareList } from '../models/compareList';
import { WithApi } from '../test/withApi';

function Location() {
  return <output aria-label="演示网址">{useLocation().search}</output>;
}
function page(path = '/course-detail-demo') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Location />
      </MemoryRouter>
    </WithApi>,
  );
}
it.each(detailDemo.courseDetailFixtures)(
  'detail demo $case maps exactly to its fixture and does not add a navigation link',
  (fixture) => {
    page(`/course-detail-demo?case=${fixture.case}`);
    expect(screen.getByRole('combobox', { name: '演示数据' })).toHaveValue(
      fixture.case,
    );
    expect(screen.getByText(fixture.notes)).toBeVisible();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '课程详情演示',
    );
    expect(
      screen.queryByRole('link', { name: '课程详情演示' }),
    ).not.toBeInTheDocument();
  },
);
it.each([
  ['empty', null],
  ['has', '已在对比中（2/4）'],
  ['full', '对比列表已满，请到课程对比页先移出一门。'],
  ['full-with', '已在对比中（4/4）'],
])(
  'detail demo compare parameter %s uses the specified simulated IDs',
  (choice, note) => {
    page(`/course-detail-demo?compare=${choice}`);
    expect(screen.getByRole('combobox', { name: '对比列表' })).toHaveValue(
      choice,
    );
    const button = screen.getByRole('button', {
      name: '加入对比',
    });
    expect((button as HTMLButtonElement).disabled).toBe(choice !== 'empty');
    if (note) expect(screen.getByText(note)).toBeVisible();
  },
);
it('detail demo unknown parameters fall back independently and agree with router case rules', () => {
  page('/COURSE-DETAIL-DEMO/?case=unknown&compare=unknown');
  expect(screen.getByRole('combobox', { name: '演示数据' })).toHaveValue(
    'cs-6140-everything',
  );
  expect(screen.getByRole('combobox', { name: '对比列表' })).toHaveValue(
    'empty',
  );
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    '课程详情演示',
  );
});
it('detail demo add callback only announces and never mutates the real compare store or navigates', async () => {
  page('/course-detail-demo?case=ds-5220-conflicts&keep=1');
  const user = userEvent.setup();
  const add = screen.getByRole('button', { name: '加入对比' });
  await user.click(add);
  await user.click(add);
  expect(
    screen.getByRole('status', { name: '课程详情演示结果' }),
  ).toHaveTextContent('演示：这里会把 c-ds-5220 加入对比');
  expect(add).toBeEnabled();
  expect(getCompareList()).toEqual([]);
  expect(screen.getByRole('status', { name: '演示网址' })).toHaveTextContent(
    '?case=ds-5220-conflicts&keep=1',
  );
});
it('detail demo open callback announces through an injected relation without changing the frozen exports', async () => {
  // All nine real exports have empty annual documents and empty legacy relations.
  // Inject only test input at the fixture-loader seam; keep the real page and R3a renderer.
  const fixture = detailDemo.courseDetailFixture('ds-5220-conflicts');
  vi.spyOn(detailDemo, 'courseDetailFixture').mockReturnValue({
    ...fixture,
    body: {
      ...fixture.body,
      prerequisites: [
        {
          course_id: 'c-cs-5800',
          primary_code: 'CS 5800',
          primary_name: 'Algorithms',
          requirement: 'required',
        },
      ],
    },
  });
  page('/course-detail-demo?case=ds-5220-conflicts');
  await userEvent.setup().click(screen.getByRole('button', { name: '查看' }));
  expect(
    screen.getByRole('status', { name: '课程详情演示结果' }),
  ).toHaveTextContent('演示：这里会打开 CS 5800');
  expect(getCompareList()).toEqual([]);
});
it.each([
  ['演示数据', 'cs-5800-identity-only'],
  ['对比列表', 'has'],
])(
  'detail demo changing %s resets disclosures and status',
  async (label, value) => {
    const { container } = page('/course-detail-demo?keep=1');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '加入对比' }));
    await user.click(
      screen.getByText('来源与说明（数据从哪来、缺了什么）', { exact: true }),
    );
    expect(
      container.querySelector('[data-course-detail] details[open]'),
    ).not.toBeNull();
    fireEvent.change(screen.getByRole('combobox', { name: label }), {
      target: { value },
    });
    expect(
      screen.getByRole('status', { name: '课程详情演示结果' }),
    ).toBeEmptyDOMElement();
    expect(
      container.querySelector('[data-course-detail] details[open]'),
    ).toBeNull();
    expect(screen.getByRole('status', { name: '演示网址' })).toHaveTextContent(
      'keep=1',
    );
  },
);
