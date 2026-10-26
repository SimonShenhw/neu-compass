import { vi } from 'vitest';
import type { DraftNode } from '../../api/draft';
import type { ApiFailure } from '../../api/load';
import {
  draftFixture,
  draftPlan,
  draftState,
  type DraftScenario,
} from '../../fixtures/draftDemo';
import type { PlanDraftProps } from './PlanDraft';

export interface DraftGolden {
  name: string;
  notes: string;
  props: DraftScenario;
  visible: Record<string, unknown>[];
}
const expected = import.meta.glob('../../fixtures/draft/expected/*.json', {
  eager: true,
  import: 'default',
});
const vectors = (name: string) =>
  expected[`../../fixtures/draft/expected/${name}.json`];
export const draftGoldens = Object.values(expected).filter(
  (v) => !Array.isArray(v),
) as DraftGolden[];
export const failureVectors = vectors('failure-vectors') as {
  failure: ApiFailure;
  text: string;
  retry: boolean;
}[];
export const treeVectors = vectors('tree-vectors') as {
  node: DraftNode;
  lines: string[];
}[];

// A fresh copy of a fixture's answer body, for a test to edit.
export const answerOf = (name: string) =>
  structuredClone(draftFixture(name).body) as Record<string, unknown>;

// The props a scene gives the component, with spies for the callbacks; fixtures are copied so a test can edit them.
export function draftProps(
  name = 'standard-mixed',
  overrides: Partial<PlanDraftProps> = {},
): PlanDraftProps {
  const golden = draftGoldens.find((g) => g.name === name);
  if (!golden) throw new Error(`Unknown draft scene ${name}`);
  return {
    plan: structuredClone(draftPlan(golden.props.plan)),
    planContentSha256: golden.props.planContentSha256,
    ...structuredClone(draftState(golden.props)),
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onRetry: vi.fn(),
    onViewCourse: vi.fn(),
    ...overrides,
  };
}

// Everything shown with a data-kind, in document order, in the shape of expected/<scene>.json's `visible`.
export function readDraftDom(root: HTMLElement) {
  const result: Record<string, unknown>[] = [];
  for (const node of root.querySelectorAll<HTMLElement>('[data-kind]')) {
    const kind = node.dataset.kind!;
    const item: Record<string, unknown> = { kind };
    if (kind === 'textarea') {
      const area = node as HTMLTextAreaElement;
      item.label = area.labels[0]?.textContent ?? null;
      item.max_length = area.maxLength;
    } else if (kind === 'tree') {
      item.lines = [...node.querySelectorAll('[data-line]')].map(
        (line) => line.textContent,
      );
    } else {
      if (kind === 'notice') item.level = node.dataset.level;
      item.text = node.textContent;
      if (kind === 'button') {
        item.action = node.dataset.action;
        if (node.dataset.action === 'add')
          item.disabled = node.getAttribute('aria-disabled') === 'true';
        if (node.dataset.courseId !== undefined)
          item.course_id = node.dataset.courseId;
      }
    }
    result.push(item);
  }
  return result;
}
