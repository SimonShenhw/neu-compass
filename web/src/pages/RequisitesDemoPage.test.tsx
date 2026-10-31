import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { expect, it } from 'vitest';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { requisitesFixtures } from '../fixtures/requisitesDemo';
import {
  YEAR_EMPTY,
  YEAR_LABEL,
} from '../features/requisites/CourseRequisites';
import { choose } from '../features/requisites/requisitesTestUtils';
import { WithApi } from '../test/withApi';

function Location() {
  return <output aria-label="演示网址">{useLocation().search}</output>;
}
function page(path = '/requisites-demo') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Location />
      </MemoryRouter>
    </WithApi>,
  );
}
it.each(requisitesFixtures)(
  'demo case $case selects its exact export and notes',
  (fixture) => {
    page(`/requisites-demo?case=${fixture.case}`);
    expect(screen.getByRole('combobox', { name: '演示数据' })).toHaveValue(
      fixture.case,
    );
    expect(screen.getByText(fixture.notes)).toBeVisible();
    expect(
      screen.getByRole('heading', {
        name: `${fixture.body.primary_code}${fixture.body.primary_name}`,
      }),
    ).toBeVisible();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '先修要求演示',
    );
    expect(
      screen.queryByRole('link', { name: '先修要求演示' }),
    ).not.toBeInTheDocument();
  },
);
it.each(['/REQUISITES-DEMO/?case=unknown', '/requisites-demo'])(
  'demo defaults and unknown inputs fall back safely: %s',
  (path) => {
    page(path);
    expect(screen.getByRole('combobox', { name: '演示数据' })).toHaveValue(
      'cs-6140-two-years',
    );
    expect(
      screen.getByRole('combobox', {
        name: (name) => name.startsWith(YEAR_LABEL),
      }),
    ).toHaveTextContent(YEAR_EMPTY);
  },
);
it('demo resets selections and navigation status on case changes; both navigation paths only announce', async () => {
  page('/requisites-demo?case=cs-6140-two-years&keep=1');
  const user = userEvent.setup();
  await choose(YEAR_LABEL, 'Catalog 2026-2027（校区和个人路径未声明）');
  await user.click(screen.getByRole('button', { name: '查看 DS 5220' }));
  expect(
    screen.getByRole('status', { name: '课程导航演示结果' }),
  ).toHaveTextContent('演示：这里会打开 DS 5220');
  await user.click(
    screen
      .getAllByRole('button', { name: /^查看 / })
      .find((button) => button.dataset.part === 'legacy')!,
  );
  expect(
    screen.getByRole('status', { name: '课程导航演示结果' }),
  ).toHaveTextContent('演示：这里会打开 CS 5100');
  const selector = screen.getByRole('combobox', { name: '演示数据' });
  fireEvent.change(selector, {
    target: { value: 'derived-identity-mismatch' },
  });
  expect(
    screen.getByRole('status', { name: '课程导航演示结果' }),
  ).toBeEmptyDOMElement();
  fireEvent.change(selector, { target: { value: 'cs-6140-two-years' } });
  expect(
    screen.getByRole('combobox', {
      name: (name) => name.startsWith(YEAR_LABEL),
    }),
  ).toHaveTextContent(YEAR_EMPTY);
  expect(screen.getByRole('status', { name: '演示网址' })).toHaveTextContent(
    '?case=cs-6140-two-years&keep=1',
  );
});
