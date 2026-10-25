import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import { apiError, fakeApi, json, livePage } from '../test/fakeApi';

// The shell's 「刷新页面内容」 and its note on content shown from before (R5d), on the live pages.
const NOTE =
  '有些内容这次没能更新，显示的是上次加载的版本；可以点「刷新页面内容」再试。';
const intro = privacy.body.intro;
// The desktop sidebar (a page may have an aside of its own, as Co-op's does).
const sidebar = () =>
  screen.getByRole('navigation', { name: '主导航' }).closest('aside')!;
const refresh = () =>
  userEvent.click(
    within(sidebar()).getByRole('button', { name: '刷新页面内容' }),
  );

it('the note is the first thing in <main>, in its own words, so a phone shows it too', async () => {
  let tries = 0;
  fakeApi(({ path }) =>
    path === '/privacy'
      ? tries++
        ? apiError(503, 'service_unavailable', 'down')
        : json(privacy.body)
      : json(null, 404),
  );
  livePage('/privacy');
  await screen.findByText(intro);
  await refresh();
  const main = screen.getByRole('main');
  const note = await within(main).findByText(NOTE);
  expect(main.firstElementChild).toContainElement(note);
});

it('on a page with nothing of its own, a refresh the API could not answer still says so: the shell’s /config counts', async () => {
  fakeApi(({ path }) =>
    path === '/config'
      ? apiError(503, 'service_unavailable', 'down')
      : json(null, 404),
  );
  livePage('/programs');
  await refresh();
  expect(
    await within(screen.getByRole('main')).findByText(NOTE),
  ).toBeInTheDocument();
});

it('the mobile menu’s 刷新页面内容 asks again as well', async () => {
  const user = userEvent.setup();
  const calls = fakeApi(({ path }) =>
    path === '/privacy' ? json(privacy.body) : json(null, 404),
  );
  livePage('/privacy');
  await screen.findByText(intro);
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }));
  await user.click(
    within(screen.getByRole('dialog', { name: '导航菜单' })).getByRole(
      'button',
      { name: '刷新页面内容' },
    ),
  );
  await waitFor(() => expect(calls.count('GET', '/privacy')).toBe(2));
});

it('刷新页面内容 asks again only what is on screen; a page left is asked when it is shown again', async () => {
  const user = userEvent.setup();
  const calls = fakeApi(({ path }) =>
    path === '/privacy' ? json(privacy.body) : json(null, 404),
  );
  livePage('/privacy');
  await screen.findByText(intro);
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await refresh();
  // The shell's /config is on screen everywhere: once it has been asked again, so would anything else have been.
  await waitFor(() => expect(calls.count('GET', '/config')).toBe(1));
  expect(calls.count('GET', '/privacy')).toBe(1);
  await user.click(within(sidebar()).getByRole('link', { name: /数据与隐私/ }));
  await waitFor(() => expect(calls.count('GET', '/privacy')).toBe(2));
});
