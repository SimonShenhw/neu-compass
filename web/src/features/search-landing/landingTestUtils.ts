import type { LandingSources } from '../../fixtures/landingDemo';
import { fixtureLoad } from '../../fixtures/landingDemo';
import type { Load } from '../../api/load';

export interface LandingExpected {
  name: string;
  sources: LandingSources;
  visible: unknown[];
}
export const landingExpected = Object.values(
  import.meta.glob<LandingExpected>(
    [
      '../../fixtures/landing/expected/*.json',
      '!../../fixtures/landing/expected/*-vectors.json',
    ],
    { eager: true, import: 'default' },
  ),
);
export function settledLanding(sources: LandingSources) {
  return structuredClone({
    programs: fixtureLoad(sources.programs),
    coop: fixtureLoad(sources.coop),
    curricula: Object.fromEntries(
      Object.entries(sources.curricula).map(([id, name]) => [
        id,
        fixtureLoad(name),
      ]),
    ),
  });
}
export const ready = (data: unknown): Load => ({ status: 'ready', data });
export const failure = (status: number): Load => ({
  status: 'failed',
  failure: {
    status,
    errorType: null,
    retryAfter: null,
    invalidFields: [],
    reason: null,
  },
});
export function readLanding(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>('[data-kind]')].map(
    (e) => {
      const kind = e.dataset.kind!,
        text = e.textContent ?? '';
      if (kind === 'starter')
        return {
          kind,
          code: e.querySelector('[data-code]')!.textContent,
          prefix: e.querySelector('[data-prefix]')!.textContent,
          name: e.querySelector('[data-name]')!.textContent,
        };
      if (kind === 'coop')
        return {
          kind,
          company: e.querySelector('[data-company]')!.textContent,
          role: e.querySelector('[data-role]')!.textContent,
        };
      if (kind === 'program')
        return { kind, text, program_id: e.dataset.programId };
      if (kind === 'view') return { kind, text, course_id: e.dataset.courseId };
      if (kind === 'sample') return { kind, text, query: e.dataset.query };
      if (kind === 'button') return { kind, text, action: e.dataset.action };
      return { kind, text };
    },
  );
}
