import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from './App';
import { fakeApi, json } from './test/fakeApi';
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

it.each([
  '/',
  '/course/CS-6140',
  '/compare',
  '/programs',
  '/programs/cs-ms',
  '/coop',
  '/privacy',
])('without them the real page %s is still there', async (path) => {
  // What the pages ask gets a 404: only which page draws matters here.
  fakeApi(() => json(null, 404));
  render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
  expect(await screen.findByRole('main')).toBeInTheDocument();
  expect(screen.queryByText('404 · 找不到这个页面')).toBeNull();
});
