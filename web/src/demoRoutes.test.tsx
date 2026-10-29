import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from './App';
import { WithApi } from './test/withApi';

// App as every build has it: demoRoutes.none.tsx in demoRoutes' place (vite.config.ts, R6).
vi.mock('./demoRoutes', () => import('./demoRoutes.none'));

it.each([
  '/compare-demo',
  '/coop-demo',
  '/privacy-demo',
  '/requisites-demo',
  '/course-detail-demo',
  '/search-demo',
  '/programs-demo',
  '/programs-draft-demo',
  '/search-landing-demo',
])(
  'without the demo routes, as in every build, %s is the page not found',
  async (path) => {
    render(
      <WithApi>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </WithApi>,
    );
    // The title still names the demo here: the tests have the demo routes' titles (__DEMO_ROUTES__), builds do not.
    expect(await screen.findByText('404 · 找不到这个页面')).toBeInTheDocument();
  },
);

it('the real pages are all there without them', async () => {
  render(
    <WithApi>
      <MemoryRouter initialEntries={['/compare']}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
  expect(
    await screen.findAllByRole('heading', { name: '课程对比' }),
  ).not.toHaveLength(0);
  expect(screen.queryByText('404 · 找不到这个页面')).toBeNull();
});
