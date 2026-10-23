import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../App';
import { demoOutcome } from '../fixtures/coopDemo';
import { WithApi } from '../test/withApi';

function page(path = '/coop') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
}
it('unknown demo input safely falls back to guest with no global guest badge or upload form', () => {
  page('/COOP/?viewer=unexpected&list=unexpected&submit=unexpected');
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(screen.queryByText('$40-45/hr')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('form', { name: '分享你的 Co-op 经验' }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: '查看权限' })).toHaveTextContent(
    '你现在是游客',
  );
  expect(
    screen
      .getByRole('heading', { name: 'Co-op 经验', level: 1 })
      .closest('header'),
  ).not.toHaveTextContent('游客');
});
it('switching response scope removes old details and resets filters and private draft', async () => {
  page('/coop?viewer=member2');
  const user = userEvent.setup();
  expect(screen.getByText('$40-45/hr')).toBeInTheDocument();
  await user.type(screen.getByLabelText(/^公司/), '私有合成草稿');
  await user.type(screen.getByRole('searchbox'), 'health');
  await user.selectOptions(
    screen.getByRole('combobox', { name: '演示访客' }),
    'guest',
  );
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(screen.getByRole('searchbox')).toHaveValue('');
  expect(screen.queryByText('$40-45/hr')).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('私有合成草稿')).not.toBeInTheDocument();
  await user.selectOptions(
    screen.getByRole('combobox', { name: '演示访客' }),
    'member2',
  );
  expect(screen.getByLabelText(/^公司/)).toHaveValue('');
});
it('demo retry restores the list and login is only a local notification', async () => {
  page('/coop?list=error');
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '重试' }));
  expect(screen.getAllByRole('article')).toHaveLength(4);
  await user.click(screen.getAllByRole('button', { name: /^登录$/ })[0]!);
  expect(screen.getByRole('status', { name: '演示提示' })).toHaveTextContent(
    '未发起真实登录',
  );
});
it('demo submission waits 400ms, keeps server contribution props unchanged and discards late results after scope change', async () => {
  vi.useFakeTimers();
  try {
    page('/coop?viewer=member0');
    fireEvent.change(screen.getByLabelText(/^公司/), {
      target: { value: 'Example' },
    });
    fireEvent.change(screen.getByLabelText(/^职位/), {
      target: { value: 'Co-op' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交经验' }));
    expect(screen.getByRole('button', { name: '提交中' })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });
    expect(
      screen.queryByRole('status', { name: '投稿结果' }),
    ).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByRole('status', { name: '投稿结果' })).toHaveTextContent(
      '已私有收集',
    );
    expect(
      screen.getByText('已公开贡献：0 条 · 当前等级 0'),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^公司/), {
      target: { value: 'Example' },
    });
    fireEvent.change(screen.getByLabelText(/^职位/), {
      target: { value: 'Co-op' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交经验' }));
    fireEvent.change(screen.getByRole('combobox', { name: '演示访客' }), {
      target: { value: 'guest' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(
      screen.queryByRole('status', { name: '投稿结果' }),
    ).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
it.each([
  'pending',
  'duplicate-pending',
  'duplicate-approved',
  'duplicate-published',
  'duplicate-rejected',
  '401',
  '422',
  '503',
  'network',
])(
  'all required demo submission choices map to the fixture contract: %s',
  (choice) => {
    const result = demoOutcome(choice);
    if (choice.startsWith('duplicate-')) {
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.result.duplicate).toBe(true);
        expect(result.result.status).toBe(choice.slice(10));
      }
    } else if (choice === 'pending') {
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.result.status).toBe('pending');
    } else {
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.status).toBe(choice === 'network' ? 503 : Number(choice));
        expect(result.body === null).toBe(choice === 'network');
      }
    }
  },
);
