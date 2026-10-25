import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../App';
import {
  demoDeletion,
  demoPrivacy,
  deleteOptions,
  privacyOptions,
} from '../fixtures/privacyDemo';
import { WithApi } from '../test/withApi';
function Location() {
  return <output aria-label="演示网址">{useLocation().search}</output>;
}
function page(path = '/privacy-demo') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Location />
      </MemoryRouter>
    </WithApi>,
  );
}
it('unknown parameters fall back to guest, 90-days and ok; global badge never contradicts the demo', () => {
  page('/PRIVACY-DEMO/?viewer=unknown&privacy=unknown&delete=unknown');
  expect(screen.getByRole('combobox', { name: '演示访客' })).toHaveValue(
    'guest',
  );
  expect(screen.getByRole('combobox', { name: '演示隐私说明' })).toHaveValue(
    '90-days',
  );
  expect(screen.getByRole('combobox', { name: '演示删除结果' })).toHaveValue(
    'ok',
  );
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(
    screen.getByRole('status', { name: '当前演示访客' }),
  ).toHaveTextContent('游客');
  expect(
    screen.getByRole('heading', { level: 1 }).closest('header'),
  ).not.toHaveTextContent('游客');
  expect(
    screen.getByRole('heading', { level: 1 }).querySelector('svg'),
  ).toHaveAttribute('aria-hidden', 'true');
});
it.each(privacyOptions)(
  'privacy parameter maps to the expected response: %s',
  (choice) => {
    page(`/privacy-demo?viewer=member&privacy=${choice}`);
    const expected = demoPrivacy(choice);
    if (expected.status === 'ready' && choice !== 'unrecognised') {
      expect(screen.getAllByRole('list')).toHaveLength(4);
      expect(screen.getByRole('checkbox')).not.toBeChecked();
    } else {
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      if (choice === 'loading')
        expect(screen.getByText('正在加载')).toBeInTheDocument();
      else
        expect(
          screen.getByRole('button', { name: '重试' }),
        ).toBeInTheDocument();
    }
  },
);
it.each(deleteOptions)(
  'deletion demo %s waits 400ms and preserves result/focus when its viewer signs out',
  async (choice) => {
    vi.useFakeTimers();
    try {
      page(`/privacy-demo?viewer=member&delete=${choice}`);
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.click(
        screen.getByRole('button', { name: '删除我的账号和投稿' }),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(399);
      });
      expect(screen.getByRole('button', { name: '正在删除…' })).toBeDisabled();
      expect(
        screen.queryByRole('status', { name: '删除结果' }),
      ).not.toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      const signsOut = ['ok', 'ok-nothing', '401-stale', '401-gone'].includes(
        choice,
      );
      const notice = screen.getByRole('status', { name: '删除结果' });
      expect(notice).toHaveFocus();
      expect(
        screen.getByRole('status', { name: '当前演示访客' }),
      ).toHaveTextContent(signsOut ? '游客' : '已登录（合成）');
      expect(screen.queryByRole('checkbox') === null).toBe(signsOut);
      expect(
        screen.getByRole('status', { name: '演示网址' }),
      ).toHaveTextContent(`?viewer=member&delete=${choice}`);
      if (choice === 'network' || choice === '503')
        expect(notice).toHaveTextContent('不确定删除有没有完成');
      else {
        const outcome = demoDeletion(choice);
        expect(notice).toHaveTextContent(
          outcome.ok
            ? '你的账号'
            : outcome.status === 401
              ? '登录已经失效'
              : '什么也没删',
        );
      }
      expect(document.body.textContent).not.toMatch(
        /Unknown user\.|Cross-site request refused\.|Input should be|published_experiences/,
      );
    } finally {
      vi.useRealTimers();
    }
  },
);
it('demo retry returns the same error after 400ms and cancels on explicit scenario change', async () => {
  vi.useFakeTimers();
  try {
    page('/privacy-demo?viewer=member&privacy=error');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });
    expect(screen.getByText('正在加载')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    fireEvent.change(screen.getByRole('combobox', { name: '演示隐私说明' }), {
      target: { value: '30-days' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(screen.queryByText('正在加载')).not.toBeInTheDocument();
    expect(
      screen.getByText('提问原文：30 天，到期换成哈希。', { exact: true }),
    ).toBeInTheDocument();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  } finally {
    vi.useRealTimers();
  }
});
// Each selector that is not the viewer, so every parameter in the session key is pinned (acceptance).
it.each([
  ['演示隐私说明', '30-days'],
  ['演示删除结果', '403'],
])(
  'changing %s discards the old in-flight deletion instead of signing out the new viewer',
  async (label, value) => {
    vi.useFakeTimers();
    try {
      page('/privacy-demo?viewer=member');
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.click(
        screen.getByRole('button', { name: '删除我的账号和投稿' }),
      );
      fireEvent.change(screen.getByRole('combobox', { name: label }), {
        target: { value },
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400);
      });
      expect(
        screen.getByRole('status', { name: '当前演示访客' }),
      ).toHaveTextContent('已登录（合成）');
      expect(
        screen.queryByRole('status', { name: '删除结果' }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole('checkbox')).not.toBeChecked();
    } finally {
      vi.useRealTimers();
    }
  },
);
