import type { ApiFailure, Load } from '../api/load';
import type { SearchFixture } from './searchDemo';

export interface LandingSources {
  programs: string;
  curricula: Readonly<Record<string, string>>;
  coop: string;
}
interface ReadFixture {
  case: string;
  body: unknown;
  failure: ApiFailure | null;
}
const reads = import.meta.glob<ReadFixture>(
  ['./landing/*.json', '!./landing/chat-sample-*.json'],
  { eager: true, import: 'default' },
);
const chats = import.meta.glob<SearchFixture>('./landing/chat-sample-*.json', {
  eager: true,
  import: 'default',
});
const curricula = {
  'aai-ms': 'curriculum-aai-ms',
  'cs-ms': 'curriculum-cs-ms',
  'ds-ms': 'curriculum-ds-ms',
};
const scenarios: Record<string, Partial<LandingSources>> = {
  guest: {},
  'member-0': { coop: 'coop-member-0' },
  'member-1': { coop: 'coop-member-1' },
  'member-2': { coop: 'coop-member-2' },
  'no-programs': { programs: 'programs-empty' },
  'nothing-at-all': { programs: 'programs-empty', coop: 'coop-empty' },
  'programs-503': { programs: 'failure-503-transport' },
  'programs-429': { programs: 'failure-429' },
  'programs-malformed': { programs: 'programs-malformed' },
  'aai-not-listed': { programs: 'programs-without-aai' },
  'featured-order': { programs: 'programs-reversed' },
  'cs-curriculum-503': { curricula: { 'cs-ms': 'failure-503-transport' } },
  'cs-curriculum-404': { curricula: { 'cs-ms': 'curriculum-404' } },
  'all-curricula-504': {
    curricula: Object.fromEntries(
      Object.keys(curricula).map((id) => [id, 'failure-504-timeout']),
    ),
  },
  'cs-curriculum-malformed': {
    curricula: { 'cs-ms': 'curriculum-cs-ms-malformed' },
  },
  'cs-curriculum-text-edge': {
    curricula: { 'cs-ms': 'curriculum-cs-ms-text-edge' },
  },
  'coop-503': { coop: 'failure-503-transport' },
  'coop-502-unreadable': { coop: 'failure-502-unreadable' },
  'coop-401': { coop: 'coop-401' },
  'coop-empty': { coop: 'coop-empty' },
  'coop-one-row': { coop: 'coop-one-row' },
  'coop-text-edge': { coop: 'coop-text-edge' },
  'coop-malformed': { coop: 'coop-malformed' },
  'coop-third-row-malformed': { coop: 'coop-third-row-malformed' },
  'coop-bad-level': { coop: 'coop-bad-level' },
  'coop-empty-interview': { coop: 'coop-empty-interview' },
  'two-failures-one-notice': {
    curricula: { 'cs-ms': 'failure-503-transport' },
    coop: 'failure-503-transport',
  },
};
export const landingScenarios = Object.keys(scenarios);
export type LandingSpeed = 'normal' | 'slow' | 'instant' | 'forever';
export function landingOptions(params: URLSearchParams) {
  const scenario = params.get('scenario') ?? '';
  const speed = params.get('speed');
  return {
    scenario: Object.hasOwn(scenarios, scenario) ? scenario : 'guest',
    speed:
      (['normal', 'slow', 'instant', 'forever'] as const).find(
        (s) => s === speed,
      ) ?? 'normal',
  };
}
export function landingSources(name: string): LandingSources {
  const scenario = scenarios[name];
  if (!Object.hasOwn(scenarios, name) || !scenario)
    throw Error('Unknown synthetic landing scenario');
  return {
    programs: scenario.programs ?? 'programs',
    coop: scenario.coop ?? 'coop-guest',
    curricula: { ...curricula, ...scenario.curricula },
  };
}
export function landingFixture(name: string) {
  const fixture = reads[`./landing/${name}.json`];
  if (!fixture) throw Error('Unknown synthetic read fixture');
  return fixture;
}
export function fixtureLoad(name: string): Load {
  const f = landingFixture(name);
  return f.failure === null
    ? { status: 'ready', data: f.body }
    : { status: 'failed', failure: f.failure };
}
export function sampleChat(index: number) {
  const chat = chats[`./landing/chat-sample-${index + 1}.json`];
  if (!chat) throw Error('Unknown synthetic sample chat');
  return chat;
}
