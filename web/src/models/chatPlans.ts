// The plans the search page offers for a question (R3e), as Streamlit's selectable_chat_plans (app/chat_plan_view.py):
// a source-checked plan of this program whose ID and scope each appear once in the whole list, and only with its
// content version from the answer's plan_revisions (#36), which the question sends back as it is, so the page never
// computes Python's JSON digest.
import type { ProgramPlanDoc } from '../api/programs';
import type { Schemas } from '../api/types';
import { hash, scopeKey } from './programGuard';
import { parsePlan } from './programPlans';
import { parseCurriculum } from './programs';
import { object } from './searchGuard';

export interface ChatPlan {
  plan: ProgramPlanDoc;
  revision: string;
}
export type PlanSelection = Schemas['PlanSelection'];

// {plan_id: content version}; an entry that is not a SHA-256 is left out, so its plan cannot be chosen.
export function planRevisions(body: unknown): Readonly<Record<string, string>> {
  const revisions: Record<string, string> = {};
  if (object(body) && object(body.plan_revisions))
    for (const [planId, value] of Object.entries(body.plan_revisions))
      if (hash(value)) revisions[planId] = value;
  return revisions;
}

// Streamlit reads the plans only while the plan table is there, and offers none from a list of more than 100, nor from
// one with a document that is not a plan. An ID or a scope found twice offers neither plan, another program's
// documents counted too. (The program page's availablePlans is gentler: it drops only what is wrong, and says so.)
export function chatPlans(body: unknown, programId: string): ChatPlan[] {
  const parsed = parseCurriculum(body, programId);
  if (
    parsed.kind !== 'ok' ||
    !parsed.data.plan_schema_available ||
    parsed.data.plans.length > 100
  )
    return [];
  const mine: ProgramPlanDoc[] = [];
  const ids = new Map<string, number>();
  const scopes = new Map<string, number>();
  for (const value of parsed.data.plans) {
    const read = parsePlan(value, programId);
    if (read.kind === 'invalid') return [];
    // Another program's document reads as a plan, only not this program's: its ID and scope count all the same.
    const doc = read.kind === 'ok' ? read.plan : (value as ProgramPlanDoc);
    ids.set(doc.plan_id, (ids.get(doc.plan_id) ?? 0) + 1);
    scopes.set(scopeKey(doc), (scopes.get(scopeKey(doc)) ?? 0) + 1);
    if (read.kind === 'ok') mine.push(read.plan);
  }
  const revisions = planRevisions(body);
  return mine.flatMap((plan) =>
    plan.review_status === 'source_checked' &&
    ids.get(plan.plan_id) === 1 &&
    scopes.get(scopeKey(plan)) === 1 &&
    Object.hasOwn(revisions, plan.plan_id)
      ? [{ plan, revision: revisions[plan.plan_id]! }]
      : [],
  );
}

// The exact plan a question asks about (schemas/plan_selection.py): its scope and the version the page showed.
export function planSelection({ plan, revision }: ChatPlan): PlanSelection {
  return {
    program_id: plan.program_id,
    plan_id: plan.plan_id,
    campus: plan.campus,
    catalog_year: plan.catalog_year,
    pathway: plan.pathway,
    concentration: plan.concentration,
    plan_content_sha256: revision,
  };
}

// What the program's plan list was: Streamlit clears a chosen plan when the list changes and says so once. The content
// versions stand for the documents here (each is a document's own digest), drafts included.
export function plansSignature(body: unknown): string {
  return JSON.stringify(
    Object.entries(planRevisions(body)).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    ),
  );
}
