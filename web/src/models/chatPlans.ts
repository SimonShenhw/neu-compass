// The plans the search page offers for a question (R3e), as Streamlit's selectable_chat_plans (app/chat_plan_view.py):
// a source-checked plan of this program whose ID and scope each appear once (R4a's availablePlans), and only with its
// content version from the answer's plan_revisions (#36), which the question sends back as it is, so the page never
// computes Python's JSON digest.
import type { ProgramPlanDoc } from '../api/programs';
import type { Schemas } from '../api/types';
import { hash } from './programGuard';
import { availablePlans } from './programPlans';
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

// Streamlit reads the plans only while the plan table is there, and offers none from a list of more than 100.
export function chatPlans(body: unknown, programId: string): ChatPlan[] {
  const parsed = parseCurriculum(body, programId);
  if (
    parsed.kind !== 'ok' ||
    !parsed.data.plan_schema_available ||
    parsed.data.plans.length > 100
  )
    return [];
  const revisions = planRevisions(body);
  return availablePlans(parsed.data.plans, programId).plans.flatMap((plan) =>
    plan.review_status === 'source_checked' &&
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
