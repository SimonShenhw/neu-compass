import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Select } from './Select';
import { Toggle } from './Toggle';
import { RequisiteTree } from './RequisiteTree';
import type { RequisiteNode } from './RequisiteTree';

const projectOptions = [
  { value: 'none', label: '不指定' },
  { value: 'cs-ms', label: 'MSCS' },
];

function SelectExample() {
  const [value, setValue] = useState('none');
  return (
    <Select
      label="项目"
      value={value}
      onChange={setValue}
      options={projectOptions}
    />
  );
}
function ToggleExample() {
  const [checked, setChecked] = useState(false);
  return (
    <Toggle checked={checked} onChange={setChecked} label="只看不同的行" />
  );
}

describe('Select keyboard behavior', () => {
  it('opens, selects and closes using the keyboard', async () => {
    const user = userEvent.setup();
    render(<SelectExample />);
    const trigger = screen.getByRole('combobox', { name: /项目/ });
    await user.tab();
    expect(trigger).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await user.keyboard('{End}{Enter}');
    expect(trigger).toHaveTextContent('MSCS');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });
  it('Escape closes without changing the selected value', async () => {
    const user = userEvent.setup();
    render(<SelectExample />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveTextContent('不指定');
  });
});

it('Toggle reports and changes its state with keyboard and pointer', async () => {
  const user = userEvent.setup();
  render(<ToggleExample />);
  const toggle = screen.getByRole('switch', { name: '只看不同的行' });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  await user.tab();
  await user.keyboard(' ');
  expect(toggle).toHaveAttribute('aria-checked', 'true');
  await user.click(toggle);
  expect(toggle).toHaveAttribute('aria-checked', 'false');
});

const tree: RequisiteNode = {
  kind: 'all',
  children: [
    {
      kind: 'any',
      children: [
        {
          kind: 'course',
          code: 'CS 5800',
          title: 'Algorithms',
          minimumGrade: 'C-',
        },
        {
          kind: 'course',
          code: 'CS 7800',
          title: 'Advanced Algorithms',
          minimumGrade: 'C-',
        },
      ],
    },
    {
      kind: 'course',
      code: 'CS 5100',
      title: 'Foundations of Artificial Intelligence',
    },
  ],
};

describe('RequisiteTree', () => {
  it('keeps nested all/any groups and the minimum grade', () => {
    render(<RequisiteTree node={tree} onOpen={vi.fn()} />);
    expect(screen.getByText('都要')).toBeInTheDocument();
    expect(screen.getByText('满足其一')).toBeInTheDocument();
    expect(screen.getAllByRole('list')).toHaveLength(2);
    // Each label must sit on its own kind of group: swapping them would tell a
    // student that one course is enough where all are required.
    const group = (label: string) => {
      const parent = screen.getByText(label).parentElement;
      if (!parent) throw new Error(`no group for ${label}`);
      return within(parent);
    };
    expect(group('满足其一').getAllByRole('button')).toHaveLength(2);
    expect(
      group('满足其一').queryByRole('button', { name: /CS 5100/ }),
    ).toBeNull();
    expect(group('都要').getAllByRole('button')).toHaveLength(3);
    expect(
      within(screen.getByRole('button', { name: /CS 5800/ })).getByText(
        '最低 C-',
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(3);
  });
  it('each leaf opens the exact course by pointer or keyboard', async () => {
    const user = userEvent.setup();
    const open = vi.fn();
    render(<RequisiteTree node={tree} onOpen={open} />);
    await user.click(screen.getByRole('button', { name: /CS 7800/ }));
    expect(open).toHaveBeenLastCalledWith('CS 7800');
    screen.getByRole('button', { name: /CS 5800/ }).focus();
    await user.keyboard('{Enter}');
    expect(open).toHaveBeenLastCalledWith('CS 5800');
  });
});
