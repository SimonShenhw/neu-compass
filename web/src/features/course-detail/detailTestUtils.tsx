import userEvent from '@testing-library/user-event';
import { courseDetailFixture } from '../../fixtures/courseDetailDemo';
import { parseCourseDetail } from '../../models/courseDetail';

export const everything = courseDetailFixture('cs-6140-everything');
export const detailData = (caseName = everything.case) =>
  structuredClone(courseDetailFixture(caseName).body);
export function detailView(caseName = everything.case) {
  const result = parseCourseDetail(detailData(caseName));
  if (result.kind !== 'ok') throw Error('Expected valid fixture');
  return result.body;
}
export function setDetail(value: unknown, path: string, replacement: unknown) {
  const keys = path.split('.');
  let current = value as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    current = current[key] as Record<string, unknown>;
  current[keys.at(-1)!] = replacement;
}
export async function expandDetail(container: HTMLElement) {
  const user = userEvent.setup();
  for (const summary of container.querySelectorAll<HTMLElement>(
    'details:not([open]) > summary',
  ))
    await user.click(summary);
}
export interface DetailEvent {
  kind: string;
  depth: number;
  text?: string;
  label?: string;
  value?: string;
  code?: string;
  name?: string;
  chips?: { label: string; value: string }[];
  disabled?: boolean;
  help?: string;
  before?: string;
  after?: string;
  href?: string | null;
  items?: string[];
  badge?: string;
  semester?: string | null;
}
export function readDetail(container: HTMLElement): DetailEvent[] {
  return [...container.querySelectorAll<HTMLElement>('[data-kind]')]
    .filter((e) => {
      const panel = e.closest('[data-kind="requisites_panel"]');
      return !panel || panel === e;
    })
    .map((e) => {
      const kind = e.dataset.kind!;
      let depth = 0;
      let parent =
        kind === 'disclosure'
          ? e.parentElement?.parentElement
          : e.parentElement;
      while (parent && parent !== container) {
        if (parent.tagName === 'DETAILS') depth++;
        parent = parent.parentElement;
      }
      const base = { kind, depth };
      const text = (selector: string) =>
        e.querySelector(selector)!.textContent!;
      switch (kind) {
        case 'header':
          return {
            ...base,
            code: text('[data-code]'),
            name: text('[data-name]'),
            chips: [...e.querySelectorAll('[data-chip]')].map((chip) => ({
              label: chip.querySelector('[data-chip-label]')!.textContent!,
              value: chip.querySelector('[data-chip-value]')!.textContent!,
            })),
          };
        case 'button':
          return {
            ...base,
            text: e.textContent!,
            disabled: (e as HTMLButtonElement).disabled,
          };
        case 'note_link':
          return {
            ...base,
            before: text('[data-before]'),
            text: text('a'),
            href: e.querySelector('a')!.getAttribute('href'),
            after: text('[data-after]'),
          };
        case 'link':
          return {
            ...base,
            text: text('a'),
            href: e.querySelector('a')!.getAttribute('href'),
            after: text('[data-after]'),
          };
        case 'line':
          return {
            ...base,
            label: text('[data-label]').slice(0, -1),
            value: text('[data-value]'),
          };
        case 'pills':
          return {
            ...base,
            items: [...e.children].map((child) => child.textContent!),
          };
        case 'program_row':
          return {
            ...base,
            name: text('[data-program-name]'),
            badge: text('[data-badge]'),
            semester: e.querySelector('[data-semester]')?.textContent ?? null,
          };
        case 'requisites_panel':
          return base;
        default:
          return {
            ...base,
            text: e.textContent!,
            ...(e.hasAttribute('title')
              ? { help: e.getAttribute('title')! }
              : {}),
          };
      }
    });
}
