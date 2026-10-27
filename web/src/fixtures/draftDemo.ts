import type { ApiFailure } from '../api/load';
import type { ProgramPlanDoc } from '../api/programs';
import { availablePlans } from '../models/programPlans';
import { object, string } from '../models/searchGuard';
import { draftScenarios } from './draftScenarios';

// R4b's offline demo (/programs-draft-demo): synthetic answers of the draft API, exported from a run of the real API
// on the synthetic catalogue (draft_fixtures/make_draft_fixtures.py), copied byte for byte.
export interface DraftScenario {
  plan: { fixture: string; plan_id: string };
  planContentSha256: string;
  answer: string | null;
  status: 'idle' | 'checking';
  failure: string | null;
}
interface Fixture {
  failure: ApiFailure | null;
  body: unknown;
}
const files = import.meta.glob('./draft/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Fixture>;
export function draftFixture(name: string): Fixture {
  const result = files[`./draft/${name}.json`];
  if (!result) throw new Error(`Unknown synthetic draft fixture: ${name}`);
  return result;
}
// The plan the scene is for, checked as R4a checks a plan list (programPlans.availablePlans).
export function draftPlan(ref: DraftScenario['plan']): ProgramPlanDoc {
  const body = draftFixture(ref.fixture).body;
  if (!object(body) || !string(body.program_id) || !Array.isArray(body.plans))
    throw new Error(`Unreadable synthetic plan list: ${ref.fixture}`);
  const plan = availablePlans(body.plans, body.program_id).plans.find(
    (p) => p.plan_id === ref.plan_id,
  );
  if (!plan) throw new Error(`No synthetic plan ${ref.plan_id}`);
  return plan;
}
// What the scene gives the component once its check has come back.
export function draftState(spec: DraftScenario) {
  return {
    answer: spec.answer === null ? null : draftFixture(spec.answer).body,
    checking: spec.status === 'checking',
    failure: spec.failure === null ? null : draftFixture(spec.failure).failure,
  };
}
export const DRAFT_SPEEDS = [
  ['normal', '正常'],
  ['slow', '慢'],
  ['instant', '立即'],
  ['forever', '一直加载'],
] as const;
export type DraftSpeed = (typeof DRAFT_SPEEDS)[number][0];
// The demo's check takes this long; forever never comes back.
export const draftDelay = (speed: DraftSpeed) =>
  speed === 'forever'
    ? null
    : speed === 'instant'
      ? 0
      : speed === 'slow'
        ? 1200
        : 300;
export function draftOptions(params: URLSearchParams) {
  const candidate = params.get('scenario') ?? '';
  const scenario = Object.hasOwn(draftScenarios, candidate)
    ? (candidate as keyof typeof draftScenarios)
    : 'standard-mixed';
  const rawSpeed = params.get('speed');
  const speed: DraftSpeed =
    rawSpeed === 'slow' || rawSpeed === 'instant' || rawSpeed === 'forever'
      ? rawSpeed
      : 'normal';
  return { scenario, speed } as const;
}
