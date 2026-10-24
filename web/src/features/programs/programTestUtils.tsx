import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ProgramScenario } from '../../fixtures/programsDemo';
import { programLoad } from '../../fixtures/programsDemo';
import { ProgramList } from './ProgramList';
import {
  ProgramCurriculum,
  type ProgramCurriculumProps,
} from './ProgramCurriculum';
import { vi } from 'vitest';

export interface Golden {
  name: string;
  props: ProgramScenario;
  visible: Record<string, unknown>[];
}
export const goldens = Object.values(
  import.meta.glob('../../fixtures/programs/expected/*.json', {
    eager: true,
    import: 'default',
  }),
).filter((v) => !Array.isArray(v)) as Golden[];
export function curriculumProps(
  name = 'cs-standard-ready',
): ProgramCurriculumProps {
  const props = goldens.find((g) => g.name === name)!.props;
  if (props.view !== 'curriculum')
    throw new Error('Expected curriculum scenario');
  return {
    ...props,
    curriculum: structuredClone(programLoad(props.curriculum)),
    policies: props.policies
      ? structuredClone(programLoad(props.policies))
      : null,
    onBack: vi.fn(),
    onRefresh: vi.fn(),
    onSelectPlan: vi.fn(),
    onViewCourse: vi.fn(),
  };
}
export function renderGolden(g: Golden) {
  return render(
    g.props.view === 'list' ? (
      <ProgramList
        programs={programLoad(g.props.programs)}
        onOpenProgram={vi.fn()}
        onRetry={vi.fn()}
      />
    ) : (
      <ProgramCurriculum {...curriculumProps(g.name)} />
    ),
  );
}
export async function readProgramDom(root: HTMLElement) {
  for (const detail of root.querySelectorAll('details')) detail.open = true;
  const result: Record<string, unknown>[] = [];
  for (const node of root.querySelectorAll<HTMLElement>('[data-kind]')) {
    const kind = node.dataset.kind!;
    let depth = 0;
    let parent = node.parentElement;
    while (parent && parent !== root) {
      if (parent.tagName === 'DETAILS') depth++;
      parent = parent.parentElement;
    }
    if (kind === 'disclosure') depth--;
    const text = node.textContent ?? '';
    const item: Record<string, unknown> = { depth, kind };
    const field = (name: string) =>
      node.querySelector(`[data-${name}]`)?.textContent ?? null;
    if (kind === 'program_card')
      Object.assign(item, {
        prefix: field('prefix'),
        name: field('name'),
        count: field('count'),
      });
    else if (kind === 'header')
      Object.assign(item, { prefix: field('prefix'), name: field('name') });
    else if (kind === 'course')
      Object.assign(item, {
        code: field('code'),
        name: field('name'),
        badge: field('badge'),
        notes: field('notes'),
      });
    else if (kind === 'select') {
      const trigger = node.querySelector('button')!;
      const spans = trigger.querySelectorAll(':scope > span');
      const label = spans[0]!.textContent;
      const value = spans[1]!.textContent;
      await userEvent.click(trigger);
      const options = (await screen.findAllByRole('option')).map(
        (o) => o.textContent,
      );
      Object.assign(item, { label, value, options });
      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });
    } else {
      item.text = text;
      if (kind === 'button') {
        if (node.dataset.action) item.action = node.dataset.action;
        if (node.dataset.programId) item.program_id = node.dataset.programId;
        if (node.dataset.courseId) item.course_id = node.dataset.courseId;
      }
      if (kind === 'link') item.href = node.getAttribute('href');
    }
    result.push(item);
  }
  return result;
}
export function edit(value: unknown, path: string, replacement: unknown) {
  const keys = path.split('.');
  let cursor = value as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    cursor = cursor[key] as Record<string, unknown>;
  if (replacement === undefined) delete cursor[keys.at(-1)!];
  else cursor[keys.at(-1)!] = replacement;
}
