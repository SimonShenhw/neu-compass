import { screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { APP_FAILED } from './components/ErrorBoundary';

// The shell itself failing while it draws, with something in its message a student must never see.
vi.mock('./App', () => ({
  App: () => {
    throw new Error('boom: CS 6140 token-7f3a');
  },
}));

it('what the shell itself throws while drawing is caught at the top, in one plain sentence (R6)', async () => {
  // React reports what a boundary catches on the console; that is not what this test looks at.
  vi.spyOn(console, 'error').mockImplementation(() => {});
  document.body.innerHTML = '<div id="root"></div>';
  await import('./main');
  expect(await screen.findByRole('alert')).toHaveTextContent(APP_FAILED);
  expect(document.body).not.toHaveTextContent(/boom|token-7f3a/);
});
