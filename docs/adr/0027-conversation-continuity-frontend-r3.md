# ADR-0027: Conversation continuity (context tier) + frontend round 3

Date: 2026-06-12
Status: Accepted (deployed to NAS, live-verified)

## Context

First real multi-turn use exposed that /chat is stateless: "那这门课讲
什么内容?" after discussing AAI 6620 retrieved 10 noise courses and
answered "找不到匹配课程" — while the detail panel drifted to a noise
top-1 (BIOL 2217) and the answer text invented facts from the course
number ("6xxx 通常属于中级水平"). Two external reviews of the UI agreed
and added: the landing is an empty box, the hero banner eats the first
screen, evidence is buried, horizontal space is wasted.

## Decision 1 — conversation continuity: deterministic context tier

House style (cheap deterministic tier first, LLM only when needed):

- `ChatRequest` gains `history` (≤12 turns, ≤4000 chars each) and
  `context_course_ids` (≤10) — the previous answer's evidence, sent by
  the UI on every request.
- `rag/followup.py`: a query is a follow-up iff it contains a referent
  expression (这门课/它/this course/it/...) AND no course-code-shaped
  token. Pure regex, fully tested.
- chat `_retrieve` Tier 0: follow-up + context ids → fetch those courses
  directly, `matched_via="context"`, score=1.0, NO rejection gate (the
  referent is explicit). Falls through to alias/program/hybrid otherwise;
  a query that names its own course is never hijacked by stale context.
- The detail-panel drift fixes itself: a follow-up now resolves to the
  course under discussion, so record_search keeps the panel there.
- Upgrade path (deliberately deferred): LLM query-rewrite fallback, to be
  triggered by query_log evidence — mine for matched_via=rejected/noise
  where the previous turn had evidence.

## Decision 2 — prompt v3 (llm/prompts/chat_v3.py)

- History block (reference resolution + tone); facts still ONLY from the
  retrieved list.
- Course CONTENT now in the candidates block (topics / skills / workload
  / difficulty / prereqs) — v2 fed only code+name+credits, so "讲什么"
  had no raw material and the model padded with filler.
- Hard rule: NEVER infer difficulty/level/content from the course NUMBER;
  missing data is stated as missing.
- Did-you-mean: with weak candidates, name the 2-3 most plausible and ask
  — never bare "找不到" above an evidence panel holding ten courses.

## Decision 3 — frontend round 3

- **Landing discovery block** (app/discover_view.py, empty-chat only):
  program chips → Programs page; 入门推荐 (one sem-1 core per featured
  program) → course detail; Co-op teaser (2 rows + 🔒) → Co-op page.
- **Programs page** (app/program_view.py + api/routes/program.py:
  GET /programs, GET /programs/{id}): card grid → per-semester curriculum
  with requirement badges, 查看 hands off to the search page's detail
  panel via pending_nav flags (consumed before the nav radio
  instantiates).
- **Prereq mini-graph** (rag/prereq_graph.py): pure DOT builder rendered
  by st.graphviz_chart (client-side, zero new deps) in the detail panel.
- **Follow-up suggestion chips** under the latest answer — they ride the
  context tier, advertising the continuity feature.
- Quick wins from the external reviews: hero shrunk to a one-row strip
  (was a 26px-padding billboard), chat:detail 5:3 (was 3:2), container
  1280px, evidence auto-expanded when ≤3 with singular/plural fixed,
  neutral avatars (🎓/🧭), em-dash placeholder chips dropped when data is
  missing, placeholder text normalized.
- Corrected two review claims: streaming already existed
  (st.write_stream); "10 retrieved sources" was the UI's k=10, not
  reranker overfitting — presentation-layer change only.

## Verification

- Tests 873 → **918**, all passing (followup detector, context tier,
  history-in-prompt, payload bounds, prompt-v3 sentinels, program routes
  incl. dangling-edge skip, prereq DOT builder, hero/header updates).
- Live (NAS): the exact failing transcript now returns
  `matched_via=context`, results=[AAI 6620], and the answer covers
  content + credits + prereq from catalog data. /programs returns 4
  programs; cs-ms curriculum groups 4 semesters.
- Browser click-through: discover block (3 sections) → cs-ms curriculum
  → 查看 → search-page detail with prereq graph rendered; sample query →
  follow-up chips appear → chip click → 续聊·context badge + correct
  grounded answer.

## Notes

- The new /chat fields are additive; old clients (none exist) would 422
  only by SENDING unknown fields, not by omitting these.
- Frontend big pieces were drafted by a background agent constrained to
  new files only; wiring, ApiClient methods, router mount, and the
  rag/ files (agent lacked write permission there) were done by hand.
