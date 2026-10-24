import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import userEvent from '@testing-library/user-event';
import type { AnswerBlock, Inline } from '../../models/answerText';
import type { Turn } from '../../models/chatTurn';
import { newTurn, turnReducer } from '../../models/chatTurn';
import { searchFixture } from '../../fixtures/searchDemo';

export interface VisibleEvent {
  kind: string;
  depth: number;
  text?: string;
  blocks?: AnswerBlock[];
  open?: boolean;
  rank?: number;
  code?: string;
  name?: string;
  score?: string;
  pct?: number;
  href?: string | null;
  course_id?: string;
  disabled?: boolean;
}
export interface Scenario {
  caseName: string;
  name: string;
  turns: string[];
  feedback_enabled: boolean;
  with_reason: boolean;
  clicks: { rating: 'up' | 'down'; outcome: unknown }[];
  visible: VisibleEvent[];
  timeline: { after: string; status: Turn['status']; text: string }[][];
  next_request: {
    history: { role: string; content: string }[];
    context_course_ids: string[];
  };
}
export function loadExpected<T>(name: string): T {
  return JSON.parse(
    readFileSync(resolve('src/fixtures/search/expected', name), 'utf8'),
  ) as T;
}
export const scenarios = readdirSync(resolve('src/fixtures/search/expected'))
  .filter(
    (f) => !['answer-text-vectors.json', 'format-vectors.json'].includes(f),
  )
  .flatMap((f) => {
    const data = loadExpected<{
      name: string;
      scenarios: Omit<Scenario, 'caseName'>[];
    }>(f);
    return data.scenarios.map((s) => ({ ...s, caseName: data.name }));
  });
export function fixtureTurn(name: string, id = 1, withReason = false) {
  const f = structuredClone(searchFixture(name));
  let turn = newTurn(
    id,
    f.request.body.query,
    f.request.body.allow_feedback_capture === true,
  );
  const timeline: Scenario['timeline'][number] = [];
  if (f.failure) {
    turn = {
      ...turn,
      status: 'failed',
      failure: {
        ...f.failure,
        reason: withReason
          ? (f.proposed_reason ?? f.failure.reason)
          : f.failure.reason,
      },
    };
    timeline.push({ after: 'refusal', status: turn.status, text: turn.text });
  } else
    for (const e of f.events) {
      turn = turnReducer(turn, e);
      timeline.push({ after: e.type, status: turn.status, text: turn.text });
      if (e.type === 'error' || e.type === 'done') break;
    }
  return { turn, timeline };
}
export const settledTurns = (scenario: Scenario) =>
  scenario.turns.map(
    (name, i) => fixtureTurn(name, i + 1, scenario.with_reason).turn,
  );
export function defaultDisclosures(container: HTMLElement) {
  return new Map(
    [...container.querySelectorAll('details')].map((d) => [d, d.open]),
  );
}
export async function expandSearch(container: HTMLElement) {
  const user = userEvent.setup();
  for (const node of container.querySelectorAll(
    'details:not([open]) > summary',
  ))
    await user.click(node);
}
function readInlines(parent: Element): Inline[] {
  const out: Inline[] = [];
  for (const node of parent.childNodes) {
    let inline: Inline;
    if (node.nodeType === Node.TEXT_NODE)
      inline = { t: 'text', v: node.textContent! };
    else {
      const e = node as Element;
      if (e.tagName === 'STRONG') inline = { t: 'strong', c: readInlines(e) };
      else if (e.tagName === 'CODE') inline = { t: 'code', v: e.textContent! };
      else if (e.tagName === 'A')
        inline = {
          t: 'link',
          v: e.textContent!,
          href: e.getAttribute('href')!,
        };
      else throw new Error('Unexpected inline element ' + e.tagName);
    }
    const previous = out.at(-1);
    if (inline.t === 'text' && previous?.t === 'text') previous.v += inline.v;
    else out.push(inline);
  }
  return out;
}
export function readAnswerDOM(parent: Element): AnswerBlock[] {
  return [...parent.children].map((e) => {
    const type = e.getAttribute('data-answer-block');
    if (type === 'code') return { type, text: e.textContent! };
    if (type === 'list')
      return {
        type,
        ordered: e.tagName === 'OL',
        start: e.tagName === 'OL' ? Number(e.getAttribute('start')) : null,
        items: [...e.children].map(readInlines),
      };
    if (type === 'heading' || type === 'paragraph')
      return { type, inlines: readInlines(e) };
    throw new Error('Unexpected answer block');
  });
}
export function readSearch(
  container: HTMLElement,
  defaults: Map<HTMLDetailsElement, boolean>,
): VisibleEvent[] {
  return [...container.querySelectorAll<HTMLElement>('[data-kind]')].map(
    (e) => {
      const kind = e.dataset.kind!;
      let parent =
        kind === 'disclosure'
          ? e.parentElement?.parentElement
          : e.parentElement;
      let depth = 0;
      while (parent && parent !== container) {
        if (parent.tagName === 'DETAILS') depth++;
        parent = parent.parentElement;
      }
      const base = { kind, depth },
        text = e.textContent!;
      if (kind === 'answer') return { ...base, blocks: readAnswerDOM(e) };
      if (kind === 'disclosure')
        return {
          ...base,
          text,
          open: defaults.get(e.parentElement as HTMLDetailsElement)!,
        };
      if (kind === 'result')
        return {
          ...base,
          rank: Number(e.querySelector('[data-rank]')!.textContent),
          code: e.querySelector('[data-code]')!.textContent!,
          name: e.querySelector('[data-name]')!.textContent!,
          score: e.querySelector('[data-score]')!.textContent!,
          pct: Number.parseFloat(
            (e.querySelector('[data-score-bar]') as HTMLElement).style.width,
          ),
        };
      if (kind === 'link')
        return { ...base, text, href: e.getAttribute('href') };
      if (kind === 'button')
        return e.hasAttribute('data-course-id')
          ? { ...base, text, course_id: e.dataset.courseId! }
          : { ...base, text, disabled: (e as HTMLButtonElement).disabled };
      return { ...base, text };
    },
  );
}
