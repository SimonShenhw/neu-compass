import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { requisitesFixture } from '../../fixtures/requisitesDemo';
import { parseRequisites } from '../../models/requisites';
import type { RequisiteListing } from '../../api/requisites';

export const twoYears = requisitesFixture('cs-6140-two-years');
export function listing(caseName = twoYears.case): RequisiteListing {
  const result = parseRequisites(
    structuredClone(requisitesFixture(caseName).body.course_requisites),
  );
  if (result.kind !== 'ok') throw Error('Expected valid fixture');
  return result.listing;
}
export function edit(value: unknown, path: string, replacement: unknown) {
  const keys = path.split('.');
  let object = value as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    object = object[key] as Record<string, unknown>;
  object[keys.at(-1)!] = replacement;
}
export async function choose(label: string, option: string) {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole('combobox', { name: (name) => name.startsWith(label) }),
  );
  await user.click(screen.getByRole('option', { name: option }));
}
export async function expandAll(container: HTMLElement) {
  const user = userEvent.setup();
  for (const summary of container.querySelectorAll<HTMLElement>(
    'details:not([open]) > summary',
  ))
    await user.click(summary);
}
export interface Visible {
  part: string;
  depth: number;
  kind: string;
  text?: string;
  label?: string | null;
  options?: string[];
  chosen?: string;
  href?: string | null;
  opens?: string;
  code?: string | null;
  name?: string | null;
  id?: string | null;
}
export async function readVisible(container: HTMLElement): Promise<Visible[]> {
  const result: Visible[] = [];
  const user = userEvent.setup();
  for (const element of container.querySelectorAll<HTMLElement>(
    '[data-kind]',
  )) {
    const kind = element.dataset.kind!;
    const base = {
      part: element.dataset.part!,
      depth: Number(element.dataset.depth),
      kind,
    };
    if (kind === 'select') {
      const trigger = element.querySelector('button')!;
      const label = trigger.querySelector('span[id]')!.textContent!;
      await user.click(trigger);
      const options = screen.getAllByRole('option');
      result.push({
        ...base,
        label,
        options: options.map((o) => o.textContent!),
        chosen:
          options.find((o) => o.getAttribute('data-state') === 'checked')
            ?.textContent ?? '',
      });
      await user.keyboard('{Escape}');
    } else if (kind === 'legacy_row') {
      const label = element.querySelector('[data-row-label]');
      result.push(
        label
          ? {
              ...base,
              code:
                element.querySelector('[data-row-code]')?.textContent ?? null,
              name:
                element.querySelector('[data-row-name]')?.textContent ?? null,
              id: element.querySelector('[data-row-id]')?.textContent ?? null,
              label: label.textContent,
            }
          : {
              ...base,
              text: element.querySelector('[data-row-text]')!.textContent!,
              label: null,
            },
      );
    } else {
      let text = element.textContent!;
      if (element.hasAttribute('data-rule-tree'))
        text = [...element.querySelectorAll<HTMLElement>('[data-rule-line]')]
          .map(
            (line) =>
              `${'  '.repeat(Number(line.parentElement!.dataset.treeDepth))}- ${line.textContent}`,
          )
          .join('\n');
      result.push({
        ...base,
        text,
        ...(kind === 'link' ? { href: element.getAttribute('href') } : {}),
        ...(kind === 'button' ? { opens: element.dataset.opens! } : {}),
      });
    }
  }
  return result;
}
