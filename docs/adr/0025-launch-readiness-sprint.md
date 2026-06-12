# ADR-0025: Launch-readiness sprint — eval-traffic tagging, cookie sessions, ontology expansion, UI round 2

Date: 2026-06-12
Status: Accepted (deployed to NAS, live-verified)

## Context

ADR-0024 left the next quality jump gated on **real** query_log data. A
NAS audit this session found query_log held 761 rows — 100% our own
`eval_via_api.py` traffic, **zero organic users**, and no way to tell the
two apart. "Wait for data" was therefore not a waiting problem but a
distribution problem: the product had never been shared, and the telemetry
that the v0.5 plan depends on would have been polluted the moment it was.

Strategy decided with the user: polish to "comfortable to share" first,
then distribute. Four workstreams shipped together.

## Decision 1 — eval-traffic tagging (load-bearing for v0.5)

Convention: **`query_log.user_id IS NULL ⇔ organic traffic.`**

- `scripts/eval_via_api.py` sends `X-Eval-Run: <label>` on every request.
- `/search` and `/chat` store it as `user_id = 'eval:<label>'`.
- All 762 pre-existing rows were backfilled to `eval:legacy` on the NAS DB
  (2026-06-12); post-deploy smoke + the verification eval run are tagged
  `eval:smoke_postdeploy` / `eval:v041_postdeploy_sprint2`. Organic count
  was confirmed **0** at convention start — from this moment, any NULL row
  is a real user.
- v0.5 mining query: `SELECT ... FROM query_log WHERE user_id IS NULL`.

No schema change (reused the nullable user_id column); rollback = stop
sending the header.

## Decision 2 — cookie session persistence (GET /auth/me + JS cookie)

Refresh logged users out (st.session_state dies with the tab) — the #1
retention killer for distribution. Design:

- **`GET /auth/me`** (api/routes/auth.py): Bearer token → itsdangerous
  re-verification (signature + max_age) → identity + fresh
  contribution_count from the users table. 401 on missing/invalid/expired
  token or deleted user.
- **app/cookie_session.py**: Streamlit reads cookies via `st.context.cookies`
  but cannot write them; writes go through a zero-height
  `components.html` iframe running `document.cookie` against
  `window.parent.document`. Queue-then-flush state machine because login
  and logout both `st.rerun()` immediately (an inline component would be
  torn down before the browser executes it).
- Restore runs **at most once per tab** with the guard set before any
  other check — `st.context.cookies` reflects the page-load request, not
  live JS state, so without the guard a logout followed by a rerun would
  silently re-login from the stale request cookie.
- 401 from /auth/me queues a cookie **clear**; transient errors (API
  down) leave the cookie for the next full reload.
- `Secure` flag added only on https so dev preview (http) keeps working;
  SameSite=Lax; max-age = settings.session_max_age_seconds (7d).

Live-verified end-to-end on the deployed stack: stale `nc_session` cookie
→ page load → /auth/me 401 → cookie deleted by the iframe JS → page stays
guest. (Real-login persistence uses the identical write mechanism; needs
a human Google account to observe, expected to follow.)

## Decision 3 — program ontology beyond AAI

`data/program_seed/{cs_ms,ds_ms,info_ms}.json` seeded locally + on NAS
(programs: aai-ms, cs-ms, ds-ms, info-ms). Structures are **best-guess
from course numbering + public program layouts — user must verify against
official Plans of Study** (same caveat as the original AAI seed). The
Layer-2 prefix regex already knew CS/DS/INFO; no code change — the chat
Layer-3 path lit up by data alone. Live: "我是 CS 专业 第一学期选啥" →
`matched_via=program`, retrieval 1.96 ms, returns the 5 seeded sem-1
courses deterministically.

`/course/{id}` now resolves ontology context (new `CourseDetailOut`):
`program_context` (reverse lookup via new
`ProgramRepository.list_programs_for_course`) and `prerequisites` (names
batch-resolved). Both `[]` outside seeded programs — response shape is
backward-compatible (subclass of Course).

## Decision 4 — UI round 2 (用户反馈"过于简陋")

- Evidence expanders → result cards (rank chip, code, name, relative
  score bar normalized within the answer, matched_via badge) shared by
  history + live paths (`_render_evidence_block`).
- Course detail: 培养方案定位 rows (requirement-type badges: core/
  foundation/elective_pool/capstone) + 先修关系 rows with navigable 查看
  buttons.
- Hero pill count now live from `/ready` (was a hardcoded "6,469" that
  went stale every re-scrape); sidebar brand block; friendly empty state
  for the detail column; footer disclaimer (非官方 · 数据可能滞后 · F1
  合规) on both pages.

## Verification

- Tests 830 → **861**, all passing (new: tagging, /auth/me,
  cookie_session state machine, course ontology context, theme builders).
- Full v0.4 eval against the deployed NAS API:
  **R@5 0.8647 / MRR 0.9357 / p50 850.5 ms / p95 1205 ms** — identical to
  the ADR-0024 baseline (0.863 / 0.931 / 852 ms). Zero retrieval
  regression, as expected (no retrieval-path changes).
- Production: 3 containers healthy, public URLs 200, /auth/me 401
  contract verified live, query_log split clean (organic = 0 at start).

## Consequences / next

- The product is now distribution-ready from the engineering side; the
  remaining blocker for v0.5 is the user sharing it (微信群 / 同学).
- Ontology seeds need a human pass against official Plans of Study.
- Real-login cookie persistence should be observed once by the user on
  prod; any failure is isolated to the set-cookie path (clear path is
  proven).
- Deferred unchanged: gate features #10, v0.5 real-distribution eval +
  recalibration (trigger: organic query volume), complex-category 0.711
  (Layer-2 LLM hook still `llm_fn=None` in production).
