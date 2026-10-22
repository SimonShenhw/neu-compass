import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AskBar } from './AskBar';

function setup() {
  const send = vi.fn();
  render(
    <MemoryRouter>
      <AskBar onSend={send} />
    </MemoryRouter>,
  );
  return {
    user: userEvent.setup(),
    send,
    input: screen.getByRole('textbox', { name: '课程问题' }),
    button: screen.getByRole('button', { name: '发送问题' }),
  };
}

it('resets consent after sending so it applies only to this question', async () => {
  const { user, send, input, button } = setup();
  await user.type(input, 'CS 6140');
  await user.click(screen.getByRole('checkbox'));
  await user.click(button);
  expect(send).toHaveBeenLastCalledWith('CS 6140', true);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  await user.type(input, 'CS 5800');
  await user.click(button);
  expect(send).toHaveBeenLastCalledWith('CS 5800', false);
});

it('disables sending empty or whitespace text and leaves consent off', async () => {
  const { user, send, input, button } = setup();
  expect(button).toBeDisabled();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  await user.type(input, '   ');
  expect(button).toBeDisabled();
  await user.keyboard('{Enter}');
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByText(/不公开的查询日志/)).toBeInTheDocument();
});
it('Enter sends trimmed input and clears the field', async () => {
  const { user, send, input, button } = setup();
  await user.type(input, '  CS 5800  ');
  expect(button).toBeEnabled();
  await user.keyboard('{Enter}');
  expect(send).toHaveBeenCalledExactlyOnceWith('CS 5800', false);
  expect(input).toHaveValue('');
  expect(button).toBeDisabled();
});
it('Shift+Enter inserts a newline without sending', async () => {
  const { user, send, input } = setup();
  await user.type(input, '第一行');
  await user.keyboard('{Shift>}{Enter}{/Shift}');
  await user.type(input, '第二行');
  expect(input).toHaveValue('第一行\n第二行');
  expect(send).not.toHaveBeenCalled();
});
it('click sends with the explicit allow-save choice', async () => {
  const { user, send, input, button } = setup();
  await user.type(input, 'CS 6140');
  await user.click(screen.getByRole('checkbox'));
  await user.click(button);
  expect(send).toHaveBeenCalledExactlyOnceWith('CS 6140', true);
});
it('does not send while the input method is composing', async () => {
  const { user, send, input } = setup();
  await user.type(input, '算法');
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
  expect(send).not.toHaveBeenCalled();
});
