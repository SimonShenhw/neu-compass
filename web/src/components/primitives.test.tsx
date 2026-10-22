import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Plus } from 'lucide-react';
import { createRef } from 'react';
import { Button } from './Button';
import { IconButton } from './IconButton';
import { CourseCode } from './CourseCode';
import { Chips } from './Chips';
import { EmptyState } from './EmptyState';
import { DataNote } from './DataNote';

describe('Button', () => {
  it.each(['primary', 'outline', 'ghost'] as const)(
    'uses %s variant and forwards a click',
    async (variant) => {
      const click = vi.fn();
      render(
        <Button variant={variant} onClick={click}>
          操作
        </Button>,
      );
      expect(screen.getByRole('button')).toHaveClass(variant, 'default');
      await userEvent.click(screen.getByRole('button'));
      expect(click).toHaveBeenCalledTimes(1);
    },
  );
  it('supports the small size without implicit form submission', () => {
    render(<Button size="sm">小按钮</Button>);
    expect(screen.getByRole('button')).toHaveClass('sm');
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button');
  });
  it('forwards its DOM ref for keyboard focus recovery', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>操作</Button>);
    expect(ref.current).toBe(screen.getByRole('button'));
    ref.current?.focus();
    expect(screen.getByRole('button')).toHaveFocus();
  });
  it('does not fire when disabled', async () => {
    const click = vi.fn();
    render(
      <Button disabled onClick={click}>
        禁用
      </Button>,
    );
    await userEvent.click(screen.getByRole('button'));
    expect(click).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toBeDisabled();
  });
});

it('IconButton has an accessible name and forwards its action', async () => {
  const click = vi.fn();
  render(
    <IconButton aria-label="加入对比" onClick={click}>
      <Plus aria-hidden="true" />
    </IconButton>,
  );
  await userEvent.click(screen.getByRole('button', { name: '加入对比' }));
  expect(click).toHaveBeenCalledOnce();
});
it('IconButton forwards its DOM ref without losing its accessible name', () => {
  const ref = createRef<HTMLButtonElement>();
  render(
    <IconButton ref={ref} aria-label="加入对比">
      +
    </IconButton>,
  );
  expect(ref.current).toBe(screen.getByRole('button', { name: '加入对比' }));
});

it('CourseCode renders literal text, never HTML', () => {
  const { container } = render(
    <CourseCode size="lg">{'<img src=x onerror=alert(1)>'}</CourseCode>,
  );
  expect(screen.getByText('<img src=x onerror=alert(1)>')).toHaveClass('lg');
  expect(container.querySelector('img')).toBeNull();
});

it('CourseCode retains the original code', () => {
  render(<CourseCode>CS 5800</CourseCode>);
  expect(screen.getByText('CS 5800')).toBeInTheDocument();
});

describe('Chips', () => {
  it('caps nine topics at eight plus one', () => {
    const items = Array.from({ length: 9 }, (_, index) => `topic-${index}`);
    render(<Chips items={items} />);
    for (const item of items.slice(0, 8))
      expect(screen.getByText(item)).toBeInTheDocument();
    expect(screen.queryByText('topic-8')).not.toBeInTheDocument();
    expect(screen.getByLabelText('另外 1 个主题')).toHaveTextContent('+1');
  });
  it('does not add a more chip at eight', () => {
    render(
      <Chips
        items={Array.from({ length: 8 }, (_, index) => `topic-${index}`)}
      />,
    );
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });
});

it('EmptyState can render without an action', () => {
  render(<EmptyState>没有评价</EmptyState>);
  expect(screen.getByText('没有评价')).toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('EmptyState renders an optional usable action', async () => {
  const click = vi.fn();
  render(
    <EmptyState action={<Button onClick={click}>回首页</Button>}>
      空列表
    </EmptyState>,
  );
  await userEvent.click(screen.getByRole('button', { name: '回首页' }));
  expect(click).toHaveBeenCalledOnce();
});

it('DataNote is a native, initially collapsed details element', async () => {
  const { container } = render(
    <DataNote>
      <p>详细来源</p>
    </DataNote>,
  );
  const details = container.querySelector('details');
  expect(details).not.toHaveAttribute('open');
  expect(screen.getByText('详细来源')).not.toBeVisible();
  await userEvent.click(screen.getByText('数据说明'));
  expect(details).toHaveAttribute('open');
  expect(screen.getByText('详细来源')).toBeVisible();
});
