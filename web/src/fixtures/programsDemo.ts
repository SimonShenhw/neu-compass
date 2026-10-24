import type { ApiFailure, Load } from '../api/load';
import { programScenarios } from './programsScenarios';

export type ProgramScenario =
  | { view: 'list'; programs: string }
  | {
      view: 'curriculum';
      programId: string;
      curriculum: string;
      selectedPlanId: string | null;
      policies: string | null;
      planRevised: boolean;
      publicBaseUrl: string;
      planRevisions: Readonly<Record<string, string>>;
    };
interface Fixture {
  failure: ApiFailure | null;
  body: unknown;
  proposed_plan_revisions?: Record<string, string>;
}
const files = import.meta.glob('./programs/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Fixture>;
export function programFixture(name: string): Fixture {
  const result = files[`./programs/${name}.json`];
  if (!result) throw new Error(`Unknown synthetic program fixture: ${name}`);
  return result;
}
export function programLoad(name: string): Load {
  const file = programFixture(name);
  return file.failure
    ? { status: 'failed', failure: file.failure }
    : { status: 'ready', data: file.body };
}
export function programsOptions(params: URLSearchParams) {
  const candidate = params.get('scenario') ?? '';
  const scenario = Object.hasOwn(programScenarios, candidate)
    ? (candidate as keyof typeof programScenarios)
    : 'list';
  const rawSpeed = params.get('speed');
  const speed =
    rawSpeed === 'slow' || rawSpeed === 'instant' || rawSpeed === 'forever'
      ? rawSpeed
      : 'normal';
  return { scenario, speed } as const;
}
export const defaultProgramPolicy = (id: string): string | null => {
  if (id === 'cs-ms-boston-2026-2027-standard')
    return 'policies-cs-ms-standard-ready';
  if (id === 'cs-ms-boston-2026-2027-align')
    return 'policies-cs-ms-align-not-linked';
  if (id === 'cs-ms-boston-2026-2027-bridge')
    return 'policies-cs-ms-bridge-draft';
  if (id === 'cs-ms-boston-2025-2026-standard')
    return 'policies-cs-ms-2025-stale';
  if (id.startsWith('ds-ms-')) return 'policies-ds-ms-not-linked';
  return null;
};
