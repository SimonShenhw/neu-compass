import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { fakeApi, json } from '../test/fakeApi';
import { WithApi } from '../test/withApi';
import {
  APP_FAILED,
  ErrorBoundary,
  PAGE_FAILED,
  pageReload,
} from './ErrorBoundary';

// A page that fails while it draws, with something in its message a student must never see.
const SECRET = 'boom: CS 6140 token-7f3a';
vi.mock('../pages/CompareRoute', () => ({
  CompareRoute: () => {
    throw new Error(SECRET);
  },
}));

// React reports what a boundary catches on the console; that is not what these tests look at. The pages around the
// failing one get a 404 for whatever they ask.
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  fakeApi(() => json(null, 404));
});

function app(path: string) {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
}

it('a page that fails while it draws says one plain sentence in the shell, never the error, and reloading starts over', async () => {
  const reload = vi.spyOn(pageReload, 'reload').mockImplementation(() => {});
  app('/compare');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(PAGE_FAILED);
  expect(document.body).not.toHaveTextContent(/boom|token-7f3a/);
  expect(
    screen.getAllByRole('navigation', { name: '主导航' }),
  ).not.toHaveLength(0);
  await userEvent.click(
    within(alert).getByRole('button', { name: '重新加载' }),
  );
  expect(reload).toHaveBeenCalledTimes(1);
});

it('going to another address tries again', async () => {
  app('/compare');
  await screen.findByRole('alert');
  const [navigation] = screen.getAllByRole('navigation', { name: '主导航' });
  await userEvent.click(
    within(navigation!).getByRole('link', { name: '培养方案' }),
  );
  // The program list draws (here it says the 404 answering everything kept it from loading).
  expect(await screen.findByText(/无法加载培养方案列表/)).toBeInTheDocument();
  expect(screen.queryByText(PAGE_FAILED)).toBeNull();
});

it('at the top, where nothing else could be drawn, it says the page could not be', () => {
  function Shell(): never {
    throw new Error(SECRET);
  }
  render(
    <ErrorBoundary where={null}>
      <Shell />
    </ErrorBoundary>,
  );
  expect(screen.getByRole('alert')).toHaveTextContent(APP_FAILED);
  expect(document.body).not.toHaveTextContent(/boom|token-7f3a/);
});

it('while nothing failed, a new address does not draw the pages under it anew', () => {
  let mounts = 0;
  function Page() {
    useEffect(() => {
      mounts += 1;
    }, []);
    return <p>page</p>;
  }
  const { rerender } = render(
    <ErrorBoundary where="/programs/cs-ms">
      <Page />
    </ErrorBoundary>,
  );
  rerender(
    <ErrorBoundary where="/programs/ds-ms">
      <Page />
    </ErrorBoundary>,
  );
  expect(screen.getByText('page')).toBeInTheDocument();
  expect(mounts).toBe(1);
});
