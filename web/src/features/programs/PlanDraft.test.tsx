import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { PlanDraft } from './PlanDraft';
import {
  answerOf,
  draftGoldens,
  draftProps,
  readDraftDom,
} from './draftTestUtils';
import { draftScenarios } from '../../fixtures/draftScenarios';
import { draftFixture, draftState } from '../../fixtures/draftDemo';

const HEADING = '我的选课草案（只在本次会话）';
const LABEL = '课号（逗号、空格或换行分开，例如 CS 5010, CS 5800）';
const BAD_ANSWER = '草案结果的格式不对，没有显示。';
const OTHER_REVISION =
  '草案结果与当前所选方案的内容版本不一致；请刷新方案后重试，未显示旧结果。';
const countLine = () => screen.getByText(/^已填 \d+\/20 门/);

describe('draft component actual DOM reference', () => {
  it('the 29 scenes are the demo scenarios', () => {
    expect(draftGoldens.map((g) => g.name).sort()).toEqual(
      Object.keys(draftScenarios).sort(),
    );
    expect(draftGoldens).toHaveLength(29);
  });
  it.each(draftGoldens)(
    '$name matches every visible item, its order, action and course ID',
    (g) => {
      expect(draftScenarios[g.name as keyof typeof draftScenarios]).toEqual(
        g.props,
      );
      const { container } = render(<PlanDraft {...draftProps(g.name)} />);
      expect(readDraftDom(container)).toEqual(g.visible);
    },
  );
  // The reference reads only data-kind items (and the box's label), so nothing else may show any text.
  it.each(draftGoldens)(
    '$name shows no text outside the items the reference reads',
    (g) => {
      const { container } = render(<PlanDraft {...draftProps(g.name)} />);
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
      const stray: string[] = [];
      for (let node = walker.nextNode(); node; node = walker.nextNode())
        if (
          node.textContent!.trim() !== '' &&
          !node.parentElement!.closest('[data-kind], label')
        )
          stray.push(node.textContent!);
      expect(stray).toEqual([]);
    },
  );
});

it('the rule tree is one block of lines joined by newlines, indentation kept', () => {
  const { container } = render(<PlanDraft {...draftProps()} />);
  const tree = container.querySelector('[data-kind="tree"]')!;
  const lines = [...tree.querySelectorAll('[data-line]')].map(
    (l) => l.textContent,
  );
  expect(tree.tagName).toBe('PRE');
  expect(tree.textContent).toBe(lines.join('\n'));
  expect(lines[3]).toBe('  按你填的满足 — Programming design core (synthetic)');
  expect(lines[4]).toBe('    按填写计入：CS 5010');
});

it('a plan not checked against its sources shows nothing, whatever else is passed', () => {
  const props = draftProps('bridge-not-checked', {
    answer: draftFixture('draft-standard-add').body,
    checking: true,
    failure: draftFixture('draft-409-unavailable').failure,
  });
  const { container } = render(<PlanDraft {...props} />);
  expect(container).toBeEmptyDOMElement();
  for (const callback of [
    props.onAdd,
    props.onRemove,
    props.onClear,
    props.onRetry,
    props.onViewCourse,
  ])
    expect(callback).not.toHaveBeenCalled();
});

it('nothing follows the add button before the first check is sent', () => {
  const { container } = render(
    <PlanDraft
      {...draftProps('standard-mixed', {
        answer: null,
        checking: false,
        failure: null,
      })}
    />,
  );
  const items = readDraftDom(container);
  expect(items.at(-1)).toEqual({
    kind: 'button',
    text: '加入草案',
    action: 'add',
    disabled: false,
  });
  expect(items).toHaveLength(7);
});

describe('callbacks', () => {
  it('add sends the typed text exactly as typed and keeps it in the box', async () => {
    const props = draftProps();
    render(<PlanDraft {...props} />);
    const box = screen.getByLabelText(LABEL);
    const typed = '  cs-5010,\n\tCS 5800  ';
    fireEvent.change(box, { target: { value: typed } });
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(props.onAdd).toHaveBeenCalledExactlyOnceWith(typed);
    expect(box).toHaveValue(typed);
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(props.onAdd).toHaveBeenCalledTimes(2);
    expect(props.onClear).not.toHaveBeenCalled();
  });
  it('add with an empty box still asks: the wiring decides what an empty check means', async () => {
    const props = draftProps();
    render(<PlanDraft {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(props.onAdd).toHaveBeenCalledExactlyOnceWith('');
  });
  it('while a check is on its way add does nothing, is aria-disabled and never disabled', async () => {
    const props = draftProps('standard-checking-again');
    render(<PlanDraft {...props} />);
    const add = screen.getByRole('button', { name: '加入草案' });
    fireEvent.change(screen.getByLabelText(LABEL), {
      target: { value: 'CS 6140' },
    });
    await userEvent.click(add);
    fireEvent.keyDown(add, { key: 'Enter' });
    expect(props.onAdd).not.toHaveBeenCalled();
    expect(add).toHaveAttribute('aria-disabled', 'true');
    expect(add).not.toBeDisabled();
    expect(add).toHaveFocus();
  });
  it('no button anywhere uses the disabled attribute', () => {
    for (const name of [
      'standard-checking-again',
      'standard-409-unavailable',
      'standard-full',
    ]) {
      const { container, unmount } = render(
        <PlanDraft {...draftProps(name)} />,
      );
      expect(container.querySelectorAll('button[disabled]')).toHaveLength(0);
      unmount();
    }
  });
  it('clear empties the box and calls onClear with nothing', async () => {
    const props = draftProps();
    render(<PlanDraft {...props} />);
    const box = screen.getByLabelText(LABEL);
    fireEvent.change(box, { target: { value: 'CS 6140' } });
    const clear = screen.getByRole('button', { name: '清空草案' });
    await userEvent.click(clear);
    expect(props.onClear).toHaveBeenCalledExactlyOnceWith();
    expect(box).toHaveValue('');
    expect(clear).toHaveFocus();
    expect(props.onAdd).not.toHaveBeenCalled();
  });
  it('remove and the course page buttons pass that row’s course ID', async () => {
    const props = draftProps();
    render(<PlanDraft {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '移除 CS 5800' }));
    expect(props.onRemove).toHaveBeenCalledExactlyOnceWith('c-cs-5800');
    await userEvent.click(
      screen.getByRole('button', { name: 'EECE 5644 · 课程页／年度先修' }),
    );
    expect(props.onViewCourse).toHaveBeenCalledExactlyOnceWith('c-eece-5644');
    expect(props.onRemove).toHaveBeenCalledTimes(1);
    expect(props.onAdd).not.toHaveBeenCalled();
  });
  it('retry calls onRetry with nothing', async () => {
    const props = draftProps('standard-409-unavailable');
    render(<PlanDraft {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '重新核对' }));
    expect(props.onRetry).toHaveBeenCalledExactlyOnceWith();
    expect(props.onAdd).not.toHaveBeenCalled();
  });
  it('the box takes at most 4000 characters and is labelled', () => {
    render(<PlanDraft {...draftProps()} />);
    expect(screen.getByLabelText(LABEL)).toHaveAttribute('maxlength', '4000');
  });
});

describe('focus', () => {
  it('remove first moves focus to the course count, without scrolling, then calls onRemove', async () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    let focusedFirst: Element | null = null;
    const props = draftProps('standard-mixed', {
      onRemove: vi.fn(() => {
        focusedFirst = document.activeElement;
      }),
    });
    const { rerender } = render(<PlanDraft {...props} />);
    const count = countLine();
    await userEvent.click(screen.getByRole('button', { name: '移除 CS 6140' }));
    expect(focusedFirst).toBe(count);
    expect(focus.mock.contexts.at(-1)).toBe(count);
    expect(focus.mock.lastCall).toEqual([{ preventScroll: true }]);
    // The answer without that course comes back: focus stays on the same line, now with the new count.
    rerender(
      <PlanDraft {...props} answer={draftFixture('draft-standard-add').body} />,
    );
    expect(countLine()).toBe(count);
    expect(count).toHaveFocus();
    expect(count).toHaveTextContent('已填 2/20 门');
    expect(screen.queryByRole('button', { name: '移除 CS 6140' })).toBeNull();
  });
  it('retry first moves focus to the heading, without scrolling, then calls onRetry', async () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    let focusedFirst: Element | null = null;
    const props = draftProps('standard-409-unavailable', {
      onRetry: vi.fn(() => {
        focusedFirst = document.activeElement;
      }),
    });
    const { rerender } = render(<PlanDraft {...props} />);
    const heading = screen.getByRole('heading', { level: 3, name: HEADING });
    await userEvent.click(screen.getByRole('button', { name: '重新核对' }));
    expect(focusedFirst).toBe(heading);
    expect(focus.mock.contexts.at(-1)).toBe(heading);
    expect(focus.mock.lastCall).toEqual([{ preventScroll: true }]);
    rerender(<PlanDraft {...props} failure={null} />);
    expect(screen.queryByRole('button', { name: '重新核对' })).toBeNull();
    expect(heading).toHaveFocus();
  });
  it('add keeps focus on its button through the check and its answer', async () => {
    const props = draftProps('standard-add');
    const { rerender } = render(<PlanDraft {...props} />);
    const add = screen.getByRole('button', { name: '加入草案' });
    await userEvent.click(add);
    expect(add).toHaveFocus();
    rerender(<PlanDraft {...props} checking />);
    expect(add).toHaveFocus();
    rerender(
      <PlanDraft
        {...props}
        answer={draftFixture('draft-standard-mixed').body}
      />,
    );
    expect(add).toHaveFocus();
  });
  it('the heading and the course count take focus from the page but are not Tab stops', async () => {
    render(<PlanDraft {...draftProps()} />);
    expect(
      screen.getByRole('heading', { level: 3, name: HEADING }),
    ).toHaveAttribute('tabindex', '-1');
    expect(countLine()).toHaveAttribute('tabindex', '-1');
    await userEvent.tab();
    expect(screen.getByRole('button', { name: '清空草案' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByLabelText(LABEL)).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('button', { name: '加入草案' })).toHaveFocus();
    await userEvent.tab();
    expect(
      screen.getByRole('button', { name: 'CS 5010 · 课程页／年度先修' }),
    ).toHaveFocus();
  });
});

it('every answer text is literal: markup, links and scripts stay text, and there is no anchor', () => {
  const markup = [
    '<b>x</b>',
    '[链接](https://example.com)',
    'javascript:alert(1)',
    '<img src=x>',
  ].join(' ');
  const answer = answerOf('draft-standard-notices');
  const courses = answer.courses as { name: string }[];
  courses[0]!.name = `课名 ${markup}`;
  const notices = answer.notices as {
    text: string;
    candidates: { name: string }[];
  }[];
  notices[0]!.text = `提示 ${markup}`;
  const ambiguous = notices.find((n) => n.candidates.length > 0)!;
  ambiguous.candidates[0]!.name = `候选 ${markup}`;
  const root = (answer.result as { root: Record<string, unknown> }).root;
  root.label = `规则 ${markup}`;
  root.reasons = [`原因 ${markup}`];
  (answer.result as { unplaced: string[] }).unplaced = [`没写到 ${markup}`];
  const { container } = render(
    <PlanDraft {...draftProps('standard-notices', { answer })} />,
  );
  for (const text of [
    `${(answer.courses as { code: string }[])[0]!.code} · 课名 ${markup} · 4 学分`,
    `提示 ${markup}`,
    `${(ambiguous.candidates[0] as unknown as { code: string }).code} · 候选 ${markup}`,
    `方案里没有写到：没写到 ${markup}`,
  ])
    expect(screen.getByText(text)).toBeInTheDocument();
  const tree = container.querySelector('[data-kind="tree"]')!.textContent;
  expect(tree).toContain(`规则 ${markup}`);
  expect(tree).toContain(`  原因：原因 ${markup}`);
  expect(container.querySelectorAll('a, b, img, script, [href]')).toHaveLength(
    0,
  );
});

it('long course names, notices and rule lines keep their line breaks and spaces', () => {
  const { container } = render(
    <PlanDraft {...draftProps('standard-text-edge')} />,
  );
  const course = container.querySelector('[data-kind="course"]')!;
  expect(course.textContent).toBe(
    'CS 5010 · Line one\nline two  with  spaces <b>bold</b> [x](https://example.com) · 4 学分',
  );
  expect(container.querySelector('a')).toBeNull();
});

describe('the answer is checked before any of it shows', () => {
  it('an answer that is not the shape shows only one warning, nothing of the answer', () => {
    const answer = answerOf('draft-standard-mixed');
    delete answer.result;
    const { container } = render(
      <PlanDraft {...draftProps('standard-mixed', { answer })} />,
    );
    const items = readDraftDom(container);
    expect(items.at(-1)).toEqual({ kind: 'warning', text: BAD_ANSWER });
    expect(items.filter((i) => i.kind === 'course')).toHaveLength(0);
    expect(screen.getByRole('alert')).toHaveTextContent(BAD_ANSWER);
  });
  it.each([
    ['another version', 'f'.repeat(64)],
    ['an invalid version on the page', 'not-a-version'],
    ['no version on the page', ''],
  ])(
    'an answer for %s shows the version warning and nothing of the answer',
    (_, version) => {
      const { container } = render(
        <PlanDraft
          {...draftProps('standard-mixed', { planContentSha256: version })}
        />,
      );
      const items = readDraftDom(container);
      expect(items.at(-1)).toEqual({ kind: 'warning', text: OTHER_REVISION });
      expect(items.filter((i) => i.kind === 'count')).toHaveLength(0);
    },
  );
  it('keys the answer does not know yet change nothing', () => {
    const answer = answerOf('draft-standard-notices');
    answer.extra = { nested: true };
    (answer.courses as Record<string, unknown>[])[0]!.extra = 1;
    (answer.notices as Record<string, unknown>[])[0]!.extra = 'x';
    const result = answer.result as Record<string, unknown>;
    result.extra = [];
    (result.root as Record<string, unknown>).extra = null;
    (result.summary_counts as Record<string, unknown>).extra = -1;
    const plain = render(<PlanDraft {...draftProps('standard-notices')} />);
    const before = readDraftDom(plain.container);
    plain.unmount();
    const { container } = render(
      <PlanDraft {...draftProps('standard-notices', { answer })} />,
    );
    expect(readDraftDom(container)).toEqual(before);
  });
  it('a new answer replaces the notices: the next one has its own or none', () => {
    const props = draftProps('standard-notices');
    const { rerender } = render(<PlanDraft {...props} />);
    expect(
      screen.getAllByText(/./, { selector: '[data-kind="notice"]' }).length,
    ).toBeGreaterThan(5);
    rerender(
      <PlanDraft {...props} answer={draftFixture('draft-standard-add').body} />,
    );
    expect(document.querySelectorAll('[data-kind="notice"]')).toHaveLength(0);
  });
});

describe('what a screen reader hears', () => {
  it('the checking line is in a status region that is there before and after it', () => {
    const props = draftProps('standard-add');
    const { rerender } = render(<PlanDraft {...props} />);
    const status = screen.getByRole('status');
    expect(status).toBeEmptyDOMElement();
    rerender(<PlanDraft {...props} checking />);
    expect(screen.getByRole('status')).toBe(status);
    expect(status).toHaveTextContent('正在核对课程…');
    rerender(<PlanDraft {...props} />);
    expect(status).toBeEmptyDOMElement();
  });
  it('the notices and the course count are in one polite live region that stays across answers', () => {
    const props = draftProps('standard-add');
    const { container, rerender } = render(<PlanDraft {...props} />);
    const live = container.querySelector('[aria-live="polite"]')!;
    expect(live).toContainElement(countLine());
    rerender(
      <PlanDraft
        {...props}
        answer={draftFixture('draft-standard-notices').body}
      />,
    );
    expect(container.querySelector('[aria-live="polite"]')).toBe(live);
    const notices = live.querySelectorAll('[data-kind="notice"]');
    expect(notices.length).toBeGreaterThan(5);
    expect(live).toContainElement(countLine());
    expect(
      within(live as HTMLElement).queryByRole('button'),
    ).not.toBeInTheDocument();
  });
  it('the failure is an alert and its retry button follows it', () => {
    render(<PlanDraft {...draftProps('standard-504-timeout')} />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      '无法核对草案。请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
    );
    expect(screen.getByRole('button', { name: '重新核对' })).toBeVisible();
  });
  it('the draft is a region named by its heading', () => {
    render(<PlanDraft {...draftProps()} />);
    expect(screen.getByRole('region', { name: HEADING })).toContainElement(
      screen.getByRole('heading', { level: 3, name: HEADING }),
    );
  });
});

it('the partial-rules note shows only for a partial plan', () => {
  const props = draftProps('align-mixed');
  expect(props.plan.coverage).toBe('complete');
  const { rerender } = render(<PlanDraft {...props} />);
  const partial = '这个方案只记录了部分规则；上述统计不是个人学位或注册审核。';
  expect(screen.queryByText(partial)).toBeNull();
  rerender(
    <PlanDraft {...props} plan={{ ...props.plan, coverage: 'partial' }} />,
  );
  expect(screen.getByText(partial)).toBeInTheDocument();
});

it('credits show as the record says: unknown is not zero', () => {
  const answer = answerOf('draft-standard-add');
  const courses = answer.courses as { credits: number | null }[];
  courses[0]!.credits = 0;
  courses[1]!.credits = null;
  render(<PlanDraft {...draftProps('standard-add', { answer })} />);
  expect(
    screen.getByText('CS 5010 · Programming Design Paradigm · 0 学分'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('CS 5800 · Algorithms · 学分未知'),
  ).toBeInTheDocument();
});

describe('vitest-axe', () => {
  it.each([
    'standard-notices',
    'standard-full',
    'standard-409-unavailable',
    'standard-checking-first',
    'standard-checking-again',
    'standard-text-edge',
  ])('%s has no violations', async (name) => {
    const { container } = render(<PlanDraft {...draftProps(name)} />);
    expect(
      (
        await axe(container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });
});

it('the scene state reads the answer and the failure from their own fixtures', () => {
  expect(draftState(draftScenarios['standard-409-unavailable'])).toEqual({
    answer: draftFixture('draft-standard-add').body,
    checking: false,
    failure: draftFixture('draft-409-unavailable').failure,
  });
  expect(draftState(draftScenarios['standard-checking-first'])).toEqual({
    answer: null,
    checking: true,
    failure: null,
  });
});
