# ADR-0029: Deep links — `?course=` / `?program=` in, share URLs out

Date: 2026-08-08
Status: Accepted (landed, 923 → 991 tests; verified against the real
6,469-course catalog in a live Streamlit run; NAS deploy pending)

## Context

ADR-0028 ranked the extension backlog and put deep links alone in the
"do before distributing" tier. The reasoning still holds: every piece of
state in this app lives in `st.session_state`, so the URL is a constant.
A student who finds something useful has no way to hand it to a
classmate — "look at CS 5800" degrades into "open the site, search for
it, no, the other one". Distribution without a shareable URL is
distribution of a homepage.

This ADR is the round that landed it. It is also the first change of the
post-launch backlog; nothing here touches the retrieval path, so the
R@5 0.8628 / MRR 0.9293 / p50 851ms baseline is untouched by
construction (no eval re-run needed — see "Not measured" below).

## Decision

**A deep link is two halves, and shipping one is shipping nothing.**
A link the app can consume but never produce cannot spread; a link it
produces but mis-consumes is worse than none. Both landed together.

### Consume — `app/deep_links.py::apply_deep_link`

Called from the pre-radio block of `streamlit_app.render()`, wedged into
a window bounded on both sides:

- **After `handle_oauth_callback()`** — that function calls
  `st.query_params.clear()` on *every* exit path, so a read placed
  before it sees params on a normal visit and an empty dict on an OAuth
  return. (ADR-0028 flagged this trap; it is real.)
- **Before `st.sidebar.radio(..., key="nav_page")`** — routing means
  writing `nav_page`, and writing a widget-bound key after its widget
  rendered raises `StreamlitAPIException`. Same rule that governs the
  `pending_nav_*` flags and the filter-clear callback.

Applied **once per session**, guarded by a `_deep_link_applied` flag.
Not by clearing the URL: the param is what makes the address bar
shareable and a refresh reproducible. Without the flag, every Streamlit
rerun — i.e. every click — would yank the user back to the linked
course. Verified live: after arriving via `?course=CS-5800` and clicking
into another course, the panel stays put while the URL keeps the param.

A **transient API failure does not burn the flag.** The dominant failure
mode is a student clicking a shared link while the API is still warming
(bge-m3 cold start is ~70s), and settling there would kill the link
permanently for exactly the user the feature exists to serve. Cost: with
a hard-down API, each rerun retries. Mirrors `program_view`'s "failures
are not cached so a warming API recovers".

### Resolve — `GET /resolve/course?ref=...` (new route)

Refs carry the human code (`CS-5800`), an internal id (`neu-cs-5800`),
or an approved alias (`Algo`, `应用 AI`). Resolution is
`rag.query_normalizer.resolve_course_ref`: internal-id tier first, then
the same `v_course_lookup` alias tier `/search` stage 1 uses, after
undoing the separator a URL puts where the code has a space (`-`, `_`,
`+`).

**Why a new route instead of reusing `POST /search`,** whose stage 1
*is* the alias tier:

1. **query_log pollution.** `/search` logs every call. Deep-link
   resolutions are machine traffic, not questions. Mixing them in would
   corrupt the organic-query signal that the entire distribution push
   exists to collect — the same telemetry `user_id IS NULL` already
   protects from eval traffic.
2. **Cost.** An alias *miss* in `/search` falls through to embed + BM25 +
   cross-encoder rerank, possibly plus a HyDE Gemini rescue: ~850ms p50
   on the NAS to answer "is this link valid?".
3. **Coverage.** A raw internal `course_id` is not in `v_course_lookup`
   at all, so the alias tier alone cannot resolve one.

Always 200; an unresolvable ref returns `matches: []`. A dead link is an
ordinary outcome, and every UI call site reads `ApiError` as "the
backend is down" — a 404 here would be a lie told in the user's
direction. `matches` is a list because a ref can be ambiguous; the UI
opens the first and names the rest.

**Programs need no route.** The UI already holds the full `/programs`
list per tab, so `match_program_ref` is a local scan accepting the
program_id (`cs-ms`) or the prefix (`INFO`). An ambiguous prefix
resolves to nothing rather than to an arbitrary winner.

### Produce — share boxes

`st.expander` + `st.code` (which carries a hover copy button for free)
in the course detail panel and the program curriculum view. New
`PUBLIC_BASE_URL` setting, tracked **separately from**
`GOOGLE_OAUTH_REDIRECT_URI` despite being the same string today: that
one has already moved once (postmortem_week7), and coupling a growth
feature to an auth config is how you discover the coupling in
production.

## Deliberately not done

- **URL rewriting as the user navigates.** Assigning to
  `st.query_params` triggers a rerun; a state→URL sync loop is one
  missed equality check away from an infinite rerun. The explicit share
  box puts the identical link in the clipboard with none of that risk.
- **Status filtering on resolve.** Matches `GET /course/{id}` and
  `/search`'s own alias path: this is an id lookup, not a search.
  ADR-0013's "pending courses must not leak" is enforced on the
  retrieval legs, and `v_course_lookup` already excludes
  `review_status='pending'` aliases — verified by test.
- **Bounded retry on a hard-down API.** Extra state for a case the
  warming-API tradeoff above deliberately favors. Revisit if the UI ever
  outlives the API for long stretches.

## Two hardening fixes found by self-review, not by tests

1. **Markdown injection through the ref.** The ref is user-controlled and
   echoed back inside a markdown code span in our own warning box.
   Streamlit blocks raw HTML, but a backtick closes the span — so
   `?course=x`​`[点这里](https://evil.example)`​` renders a clickable
   link inside chrome the user has every reason to trust. Phishing on a
   URL anyone can forge. `_ref_label` strips backticks and caps length;
   the ref is still shown, so the user sees the truth.
2. **Protocol-relative share URL.** `PUBLIC_BASE_URL` is hand-edited. A
   trailing `//` collapsed the link to `//?course=...`, which browsers
   resolve against a *different* host. `rstrip("/")`, regression-tested.

Both now have named tests.

## Verification

Unit + API + UI tests: **923 → 991**, whole suite green. Beyond that,
a live run against the real catalog (model-free API via
`create_app(run_startup=False)` — the touched routes are pure SQLite,
so the 70s model warm buys nothing):

| Case | Result |
|---|---|
| `?course=CS-5800` | CS 5800 detail panel, full enrichment |
| URL after landing | keeps `?course=CS-5800` (shareable) |
| Share box content | `http://localhost:8502/?course=CS-5800` — the same URL |
| Click another course | panel moves, **no snap-back** on rerun |
| `?program=cs-ms` | CS MS curriculum, nav switched |
| `?program=INFO` (prefix) | MSIS curriculum |
| `?course=CS-9999` | warning, no crash |

Resolver against the 6,469-course catalog: `Algo`, `应用 AI`, `应用-AI`,
`5800`, `neu-cs-5800`, `CS+5800`, `cs5800` all resolve; `nonsense-xyz`
returns nothing.

**Not measured, on purpose:** retrieval quality. No hot path changed —
`/search` and `/chat` are byte-identical. The ADR-0028 lesson ("re-run
eval after ANY hot-path change, even a safe timeout") is about the hot
path; this round stays off it.

## Follow-ups this unblocks

Deep links were the gate on the ADR-0028 "first post-launch" tier.
Next, in order: **answer feedback 👍/👎** (turns organic traffic into
labeled eval pairs for v0.5), the semester planner, and RMP enrichment
driven by real `query_log` traffic — all of which need traffic that this
round is what actually generates.

Two smaller ones this round surfaced:
- `PUBLIC_BASE_URL` must be set on the NAS at deploy (compose carries it;
  a stale `.env` on the box would silently emit `localhost:8501` links).
- Bare-number aliases already work for the courses that have them seeded
  (`?course=5800` resolves), but only those — the ADR-0028
  "bare-number aliases" item is still open for the rest of the catalog.
