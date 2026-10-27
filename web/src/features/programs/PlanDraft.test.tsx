import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { PlanDraft } from './PlanDraft';
import styles from './PlanDraft.module.css';
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
const PLAN_GONE = '所选方案已经变化或不能再用，草案没有计算；请重新选择方案。';
// The course count line; its words sit in a span that each answer draws afresh.
const countLine = () =>
  document.querySelector<HTMLElement>('[data-kind="count"]')!;
const malformed = () => {
  const answer = answerOf('draft-standard-mixed');
  delete answer.result;
  return answer;
};

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
  // The reference reads only data-kind items (and the box's own label), so nothing else may show any text, neither
  // in the page nor in an attribute a browser shows.
  it.each(draftGoldens)(
    '$name shows no text outside the items the reference reads',
    (g) => {
      const { container } = render(<PlanDraft {...draftProps(g.name)} />);
      const label = container.querySelector('textarea')?.labels?.[0] ?? null;
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
      const stray: string[] = [];
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const parent = node.parentElement!;
        if (
          node.textContent!.trim() !== '' &&
          !parent.closest('[data-kind]') &&
          (label === null || parent.closest('label') !== label)
        )
          stray.push(node.textContent!);
      }
      expect(stray).toEqual([]);
      expect(
        container.querySelectorAll('[placeholder], [title], [alt]'),
      ).toHaveLength(0);
    },
  );
  // And it reads them as shown, so none of them may be hidden, from the eye or from a screen reader.
  it.each(draftGoldens)(
    '$name hides none of the items the reference reads',
    (g) => {
      const { container } = render(<PlanDraft {...draftProps(g.name)} />);
      for (const item of container.querySelectorAll('[data-kind]')) {
        expect(item).toBeVisible();
        expect(item.closest('[aria-hidden="true"]')).toBeNull();
      }
    },
  );
});

it('a notice looks like its level: the warning box and icon, or the plain box and the info icon', () => {
  const levels: string[] = [];
  for (const name of ['standard-notices', 'standard-nothing-new']) {
    const { container, unmount } = render(<PlanDraft {...draftProps(name)} />);
    for (const notice of container.querySelectorAll('[data-kind="notice"]')) {
      // The level is on the styled box that holds the icon, not on the sentence.
      const box = notice.closest<HTMLElement>('[data-level]')!;
      expect(box).toHaveClass(styles.notice!);
      const level = box.dataset.level!;
      levels.push(level);
      const icon = box.querySelector(':scope > svg');
      expect(icon, level).not.toBeNull();
      expect(icon!.getAttribute('class')).toMatch(
        level === 'warning' ? /\blucide-triangle-alert\b/ : /\blucide-info\b/,
      );
    }
    unmount();
  }
  expect(new Set(levels)).toEqual(new Set(['warning', 'info']));
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
  it('while a check is on its way retry does nothing, is aria-disabled and never disabled', async () => {
    const props = draftProps('standard-409-unavailable', { checking: true });
    const { container } = render(<PlanDraft {...props} />);
    const retry = screen.getByRole('button', { name: '重新核对' });
    await userEvent.click(retry);
    fireEvent.keyDown(retry, { key: 'Enter' });
    expect(props.onRetry).not.toHaveBeenCalled();
    expect(retry).toHaveAttribute('aria-disabled', 'true');
    expect(retry).not.toBeDisabled();
    expect(retry).toHaveFocus();
    // The last failure stays until a check succeeds (spec section 3), under the checking line.
    expect(
      readDraftDom(container)
        .slice(6, 10)
        .map((i) => (i.action ? `${i.kind}:${String(i.action)}` : i.kind)),
    ).toEqual(['button:add', 'status', 'failure', 'button:retry']);
  });
  it('no button anywhere uses the disabled attribute', () => {
    for (const props of [
      draftProps('standard-checking-again'),
      draftProps('standard-409-unavailable'),
      draftProps('standard-409-unavailable', { checking: true }),
      draftProps('standard-full'),
    ]) {
      const { container, unmount } = render(<PlanDraft {...props} />);
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

describe('the typed text', () => {
  it('stays through a check, its answer and a move straight to another checked plan', () => {
    const props = draftProps('standard-add');
    const { rerender } = render(<PlanDraft {...props} />);
    const box = screen.getByLabelText(LABEL);
    fireEvent.change(box, { target: { value: 'CS 6140, XX 1' } });
    rerender(<PlanDraft {...props} checking />);
    rerender(
      <PlanDraft {...props} answer={answerOf('draft-standard-notices')} />,
    );
    expect(box).toHaveValue('CS 6140, XX 1');
    const align = draftProps('align-mixed');
    rerender(
      <PlanDraft
        {...props}
        plan={align.plan}
        planContentSha256={align.planContentSha256}
        answer={align.answer}
      />,
    );
    expect(screen.getByLabelText(LABEL)).toBe(box);
    expect(box).toHaveValue('CS 6140, XX 1');
  });
  it('goes with a plan not checked against its sources, as on Streamlit, and does not come back', () => {
    const props = draftProps('standard-add');
    const { container, rerender } = render(<PlanDraft {...props} />);
    fireEvent.change(screen.getByLabelText(LABEL), {
      target: { value: 'CS 6140' },
    });
    const bridge = draftProps('bridge-not-checked');
    rerender(
      <PlanDraft
        {...props}
        plan={bridge.plan}
        planContentSha256={bridge.planContentSha256}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<PlanDraft {...props} />);
    expect(screen.getByLabelText(LABEL)).toHaveValue('');
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
  it('when the course count goes while it has focus, focus moves to the heading, without scrolling', async () => {
    const props = draftProps('standard-mixed');
    const { rerender } = render(<PlanDraft {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '移除 CS 6140' }));
    expect(countLine()).toHaveFocus();
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    rerender(<PlanDraft {...props} answer={malformed()} />);
    expect(countLine()).toBeNull();
    const heading = screen.getByRole('heading', { level: 3, name: HEADING });
    expect(heading).toHaveFocus();
    expect(focus.mock.contexts).toEqual([heading]);
    expect(focus.mock.lastCall).toEqual([{ preventScroll: true }]);
  });
  it('when the buttons of a course or the retry button go while one has focus, focus moves to the heading', () => {
    const props = draftProps('standard-mixed');
    const { rerender, unmount } = render(<PlanDraft {...props} />);
    screen.getByRole('button', { name: 'CS 6140 · 课程页／年度先修' }).focus();
    rerender(<PlanDraft {...props} answer={malformed()} />);
    expect(
      screen.getByRole('heading', { level: 3, name: HEADING }),
    ).toHaveFocus();
    unmount();
    // A keyboard user reached retry while it was on its way, and the check succeeds.
    const retrying = draftProps('standard-409-unavailable', { checking: true });
    const view = render(<PlanDraft {...retrying} />);
    screen.getByRole('button', { name: '重新核对' }).focus();
    view.rerender(<PlanDraft {...retrying} checking={false} failure={null} />);
    expect(screen.queryByRole('button', { name: '重新核对' })).toBeNull();
    expect(
      screen.getByRole('heading', { level: 3, name: HEADING }),
    ).toHaveFocus();
    view.unmount();
    // Or the check fails again in a way that cannot be retried: the button goes, the failure stays.
    const failing = draftProps('standard-503-transport', { checking: true });
    const again = render(<PlanDraft {...failing} />);
    screen.getByRole('button', { name: '重新核对' }).focus();
    again.rerender(
      <PlanDraft
        {...failing}
        checking={false}
        failure={draftFixture('draft-404').failure}
      />,
    );
    expect(screen.queryByRole('button', { name: '重新核对' })).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent(
      '找不到这个培养方案或方案，草案没有计算。',
    );
    expect(
      screen.getByRole('heading', { level: 3, name: HEADING }),
    ).toHaveFocus();
  });
  it('when the course count goes while nothing has focus, nothing takes it', () => {
    const props = draftProps('standard-mixed');
    const { rerender } = render(<PlanDraft {...props} />);
    expect(document.activeElement).toBe(document.body);
    rerender(<PlanDraft {...props} planContentSha256={'f'.repeat(64)} />);
    expect(countLine()).toBeNull();
    expect(document.activeElement).toBe(document.body);
  });
  // React gives focus back to the element that had it before an update, so where focus ends up shows nothing; a
  // moment of focus on the heading would still blur the box (and break an input method's composition), so the events
  // are watched too.
  it('when the course count goes while focus is elsewhere, focus stays there, not even for a moment elsewhere', async () => {
    const props = draftProps('standard-mixed');
    const { rerender } = render(<PlanDraft {...props} />);
    const box = screen.getByLabelText(LABEL);
    await userEvent.click(box);
    const headingFocused = vi.fn();
    screen
      .getByRole('heading', { level: 3, name: HEADING })
      .addEventListener('focus', headingFocused);
    const boxBlurred = vi.fn();
    box.addEventListener('blur', boxBlurred);
    rerender(<PlanDraft {...props} planContentSha256={'f'.repeat(64)} />);
    expect(countLine()).toBeNull();
    expect(box).toHaveFocus();
    expect(headingFocused).not.toHaveBeenCalled();
    expect(boxBlurred).not.toHaveBeenCalled();
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

it('a course line keeps its line breaks and spaces as text, with no anchor', () => {
  const { container } = render(
    <PlanDraft {...draftProps('standard-text-edge')} />,
  );
  const course = container.querySelector('[data-kind="course"]')!;
  expect(course.textContent).toBe(
    'CS 5010 · Line one\nline two  with  spaces <b>bold</b> [x](https://example.com) · 4 学分',
  );
  expect(container.querySelector('a')).toBeNull();
});

// jsdom applies no stylesheet, so the declarations that matter are read from the file; a line break in front, so the
// first rule starts a line like the others.
const css = `\n${readFileSync(
  resolve(process.cwd(), 'src/features/programs/PlanDraft.module.css'),
  'utf8',
)}`;
const cssRule = (selector: string) => {
  const start = css.indexOf(`\n${selector} {`);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf('}', start));
};
const cssValues = (property: string) =>
  new Set(
    [...css.matchAll(new RegExp(`${property}:\\s*([^;]+);`, 'g'))].map(
      (m) => m[1],
    ),
  );

it('the stylesheet shows line breaks and spaces and wraps long words', () => {
  expect(cssRule('.draft')).toContain('overflow-wrap: anywhere;');
  for (const selector of [
    '.note',
    '.text',
    '.alert',
    '.noticeBody p,\n.candidates',
    '.courseText',
    '.tree',
  ])
    expect(cssRule(selector), selector).toContain('white-space: pre-wrap;');
  expect(cssRule('.tree')).toContain('overflow-wrap: anywhere;');
  // And no rule anywhere in the file takes it back.
  expect(cssValues('white-space')).toEqual(new Set(['pre-wrap']));
  expect(cssValues('overflow-wrap')).toEqual(new Set(['anywhere']));
});

it('the stylesheet gives a warning notice its border and greys out a button that waits', () => {
  // The two looks of a notice hang on its box's level.
  expect(cssRule(".notice[data-level='warning']")).toContain(
    'border-color: var(--accent);',
  );
  // Add and retry while a check is on its way.
  const waiting = cssRule(
    ".add[aria-disabled='true'],\n.retry[aria-disabled='true']",
  );
  expect(waiting).toContain('cursor: not-allowed;');
  expect(waiting).toContain('opacity: 0.55;');
});

it('typing and every button keep nothing: no storage and no address', () => {
  localStorage.clear();
  sessionStorage.clear();
  const href = window.location.href;
  render(<PlanDraft {...draftProps('standard-409-unavailable')} />);
  fireEvent.change(screen.getByLabelText(LABEL), {
    target: { value: 'CS 6140' },
  });
  for (const name of [
    '加入草案',
    '移除 CS 5010',
    'CS 5800 · 课程页／年度先修',
    '重新核对',
    '清空草案',
  ])
    fireEvent.click(screen.getByRole('button', { name }));
  expect(localStorage).toHaveLength(0);
  expect(sessionStorage).toHaveLength(0);
  expect(window.location.href).toBe(href);
});

it('the draft modules keep nothing, ask nothing and interpret no HTML or Markdown', () => {
  for (const file of [
    'api/draft.ts',
    'models/planDraft.ts',
    'features/programs/PlanDraft.tsx',
    'fixtures/draftDemo.ts',
    'pages/PlanDraftDemoPage.tsx',
  ]) {
    const source = readFileSync(resolve(process.cwd(), 'src', file), 'utf8');
    expect(source, file).not.toMatch(
      /localStorage|sessionStorage|indexedDB|document\.cookie|history\.|location\.|fetch\(|console\.|dangerouslySetInnerHTML|react-markdown/,
    );
  }
});

it.each([
  'draft-409-stale',
  'draft-409-missing',
  'draft-409-draft',
  'draft-409-unusable',
])(
  'the real %s failure says the plan has changed and offers no retry',
  (name) => {
    render(
      <PlanDraft
        {...draftProps('standard-add', { failure: draftFixture(name).failure })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(PLAN_GONE);
    expect(screen.queryByRole('button', { name: '重新核对' })).toBeNull();
  },
);

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
  it('an answer shown before shows nothing of it once it no longer fits the page', () => {
    const props = draftProps('standard-mixed');
    const { container, rerender } = render(<PlanDraft {...props} />);
    const shown = () =>
      container.querySelectorAll(
        '[data-kind="course"], [data-kind="summary"], [data-kind="tree"], [data-kind="count"], [data-action="remove"]',
      ).length;
    expect(shown()).toBeGreaterThan(5);
    rerender(<PlanDraft {...props} planContentSha256={'f'.repeat(64)} />);
    expect(readDraftDom(container).at(-1)).toEqual({
      kind: 'warning',
      text: OTHER_REVISION,
    });
    expect(shown()).toBe(0);
    rerender(<PlanDraft {...props} answer={malformed()} />);
    expect(readDraftDom(container).at(-1)).toEqual({
      kind: 'warning',
      text: BAD_ANSWER,
    });
    expect(shown()).toBe(0);
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
  it('the version warning is an alert too', () => {
    render(<PlanDraft {...draftProps('standard-other-revision')} />);
    expect(screen.getByRole('alert')).toHaveTextContent(OTHER_REVISION);
  });
  // A live region speaks only when its content changes, so an outcome like the last one must be drawn afresh.
  it('a retry that fails the same way again draws its sentence afresh; the retry button and focus on it stay', () => {
    const props = draftProps('standard-503-transport');
    const { container, rerender } = render(<PlanDraft {...props} />);
    const sentence = () => container.querySelector('[data-kind="failure"]')!;
    const first = sentence();
    expect(first).toHaveAttribute('role', 'alert');
    const retry = screen.getByRole('button', { name: '重新核对' });
    rerender(<PlanDraft {...props} checking />);
    expect(sentence()).toBe(first);
    retry.focus(); // A keyboard user reaches it while the retry is on its way.
    rerender(<PlanDraft {...props} failure={{ ...props.failure! }} />);
    expect(sentence()).not.toBe(first);
    expect(sentence()).toHaveTextContent(first.textContent!);
    expect(sentence()).toHaveAttribute('role', 'alert');
    expect(screen.getByRole('button', { name: '重新核对' })).toBe(retry);
    expect(retry).toHaveFocus();
  });
  it('an answer like the last one draws its notices and the count’s words afresh; the count line stays', () => {
    const props = draftProps('standard-notices');
    const { container, rerender } = render(<PlanDraft {...props} />);
    const notices = () => [
      ...container.querySelectorAll('[data-kind="notice"]'),
    ];
    const first = notices();
    const count = countLine();
    const words = count.firstElementChild!;
    rerender(<PlanDraft {...props} checking />);
    expect(notices().every((n, i) => n === first[i])).toBe(true);
    rerender(
      <PlanDraft {...props} answer={answerOf('draft-standard-notices')} />,
    );
    const again = notices();
    expect(again.map((n) => n.textContent)).toEqual(
      first.map((n) => n.textContent),
    );
    expect(again.some((n) => first.includes(n))).toBe(false);
    expect(countLine()).toBe(count);
    expect(count.firstElementChild).not.toBe(words);
    expect(count).toHaveTextContent(words.textContent!);
  });
  it('another answer that cannot be shown draws its warning afresh', () => {
    for (const [scene, text, next] of [
      ['standard-malformed', BAD_ANSWER, malformed],
      [
        'standard-other-revision',
        OTHER_REVISION,
        () => answerOf('draft-other-revision'),
      ],
    ] as const) {
      const props = draftProps(scene);
      const { container, rerender, unmount } = render(<PlanDraft {...props} />);
      const warning = container.querySelector('[data-kind="warning"]');
      expect(warning).toHaveTextContent(text);
      rerender(<PlanDraft {...props} answer={next()} />);
      const again = container.querySelector('[data-kind="warning"]');
      expect(again).not.toBe(warning);
      expect(again).toHaveTextContent(text);
      unmount();
    }
  });
  it('a new failure draws only its sentence afresh: the notices and the count’s words stay', () => {
    const props = draftProps('standard-notices', {
      failure: draftFixture('draft-409-unavailable').failure,
    });
    const { container, rerender } = render(<PlanDraft {...props} />);
    const notices = [...container.querySelectorAll('[data-kind="notice"]')];
    const words = countLine().firstElementChild;
    const sentence = container.querySelector('[data-kind="failure"]');
    rerender(<PlanDraft {...props} failure={{ ...props.failure! }} />);
    expect(container.querySelector('[data-kind="failure"]')).not.toBe(sentence);
    expect(
      [...container.querySelectorAll('[data-kind="notice"]')].every(
        (n, i) => n === notices[i],
      ),
    ).toBe(true);
    expect(countLine().firstElementChild).toBe(words);
  });
  it('drawing again with the same answer and failure redraws nothing', () => {
    const props = draftProps('standard-notices', {
      failure: draftFixture('draft-409-unavailable').failure,
    });
    const { container, rerender } = render(<PlanDraft {...props} />);
    const before = [...container.querySelectorAll('*')];
    fireEvent.change(screen.getByLabelText(LABEL), {
      target: { value: 'CS 6140' },
    });
    rerender(<PlanDraft {...props} />);
    const after = [...container.querySelectorAll('*')];
    expect(after).toHaveLength(before.length);
    expect(after.filter((el, i) => el !== before[i])).toEqual([]);
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
