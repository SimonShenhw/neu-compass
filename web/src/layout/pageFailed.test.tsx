import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useState } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { PAGE_FAILED } from '../components/ErrorBoundary';
import type * as SearchRouteModule from '../pages/SearchRoute';
import { fakeApi, json, livePage } from '../test/fakeApi';

// The search page fails while it draws as long as `failing` says so; the comparison page fails once its button is
// pressed, or once `breakIt` is called from outside it, as data coming back after a refresh would make it fail. What
// the shell around them does (review A34).
let failing = false;
let breakIt: (() => void) | undefined;
vi.mock('../pages/SearchRoute', async (importOriginal) => {
  const original = await importOriginal<typeof SearchRouteModule>();
  return {
    ...original,
    SearchRoute: () => {
      if (failing) throw new Error('boom');
      return <original.SearchRoute />;
    },
  };
});
function Breaks() {
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    breakIt = () => setBroken(true);
    return () => {
      breakIt = undefined;
    };
  }, []);
  if (broken) throw new Error('boom');
  return (
    <button type="button" onClick={() => setBroken(true)}>
      break it
    </button>
  );
}
vi.mock('../pages/CompareRoute', () => ({ CompareRoute: Breaks }));

// React reports what a boundary catches on the console; the API answers 404 to everything.
beforeEach(() => {
  failing = false;
  vi.spyOn(console, 'error').mockImplementation(() => {});
  fakeApi(() => json(null, 404));
});

// It sent questions, into the query log too, with no page to show their answers.
it('a search page that fails while it draws takes the ask box with it, and the box comes back with the page', async () => {
  failing = true;
  livePage('/');
  expect(await screen.findByRole('alert')).toHaveTextContent(PAGE_FAILED);
  expect(screen.queryByRole('form', { name: '提问' })).toBeNull();
  failing = false;
  const [navigation] = screen.getAllByRole('navigation', { name: '主导航' });
  await userEvent.click(
    within(navigation!).getByRole('link', { name: /培养方案/ }),
  );
  await userEvent.click(
    within(navigation!).getByRole('link', { name: /课程搜索/ }),
  );
  expect(await screen.findByRole('form', { name: '提问' })).toBeInTheDocument();
  expect(screen.queryByText(PAGE_FAILED)).toBeNull();
});

// The button pressed went with the page, and focus with it to the body.
it('when a page fails on a button pressed in it, focus goes to main, without scrolling', async () => {
  livePage('/compare');
  const button = await screen.findByRole('button', { name: 'break it' });
  button.focus();
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await userEvent.keyboard('{Enter}');
  expect(await screen.findByRole('alert')).toHaveTextContent(PAGE_FAILED);
  const main = screen.getByRole('main');
  await waitFor(() => expect(main).toHaveFocus());
  expect(focus.mock.calls[focus.mock.contexts.indexOf(main)]).toEqual([
    { preventScroll: true },
  ]);
});

// Focus on what stays, as on the sidebar's 刷新页面内容 whose data made the page fail, stays there: only focus that went
// with the page goes to main (the focus rule of 10-25; recheck 1 of round 34).
it.each([
  [
    'a link in the sidebar',
    () =>
      within(
        screen.getAllByRole('navigation', { name: '主导航' })[0]!,
      ).getByRole('link', { name: /培养方案/ }),
  ],
  [
    '刷新页面内容',
    () => screen.getAllByRole('button', { name: '刷新页面内容' })[0]!,
  ],
])(
  'when a page fails while focus is on %s, which stays, focus stays there',
  async (_, target) => {
    livePage('/compare');
    await screen.findByRole('button', { name: 'break it' });
    const element = target();
    element.focus();
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    // The act runs the catch, and after it the shell's effect for the failed page: nothing more to wait for.
    act(() => breakIt!());
    expect(await screen.findByRole('alert')).toHaveTextContent(PAGE_FAILED);
    expect(element).toHaveFocus();
    expect(focus.mock.contexts).not.toContain(screen.getByRole('main'));
  },
);
