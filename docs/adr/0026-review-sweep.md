# ADR-0026: Full-project review sweep — 24 fixes in one round

Date: 2026-06-12
Status: Accepted (deployed to NAS)

## Context

Three same-day production bugs (OAuth redirect_uri mismatch, OAuth state
in session_state, pyarrow excluded from the image) shared one pattern:
**the production path had never been exercised**. Rather than keep finding
these one user-report at a time, we ran a structured sweep: four parallel
read-only review agents (UI layer / API+DB / config+packaging / RAG glue)
plus dynamic checks (container import sweep ×2, 14-case API edge battery,
full UI click-through). 30 findings, 24 fixed in this round.

## What the sweep caught (by severity)

### HIGH

1. **`deploy.ps1 -SyncData` stripped nested JSONs** — bare
   `--exclude='*.json'` matched at any depth, dropping
   `faiss_index/id_map.json` (stale copy ⇒ FAISS int ids silently map to
   WRONG course_ids) and OpenVINO `config.json` (api crash-loop). Now
   anchored to top level. *Never fired only because -SyncData hasn't been
   used since the OpenVINO export.*
2. **API-down crashed the whole UI page** — `ApiClient` wrapped only
   `TimeoutException`; `ConnectError`/`ReadError` propagated raw and every
   call site catches `ApiError` only. Now all `httpx.HTTPError` → 503/504
   `ApiError`; `chat_stream` degrades mid-stream failures to an in-stream
   `error` event (partial output preserved).
3. **Live-evidence 查看 buttons were dead** — rendered only inside
   `if prompt:`, so the click's rerun never re-instantiated them and
   Streamlit dropped the event. Fixed with `st.rerun()` after
   `add_message` (history path has stable keys).
4. **Give-to-get could never bootstrap** — GET /coop filtered ROWS by
   tier while all 30 seed rows are level 2 ⇒ anonymous/fresh users saw an
   empty list. Switched to FIELD-level redaction (server-side): everyone
   sees every row's level-0 fields; interview unlocks at tier 1, salary at
   tier 2; `visibility_level` drives 🔒 unlock hints in the UI.
5. **Co-op page rendered twice** — `"streamlit" in sys.argv[0]` run-guards
   fired on IMPORT under a running streamlit process. All three pages now
   use plain `__name__ == "__main__"`.

### MED

6. OpenVINO embedder/reranker tokenized OUTSIDE the inference lock —
   HF fast-tokenizer "Already borrowed" race under concurrent requests.
   Tokenization moved inside the lock (mirrors the pytorch backend).
7. Two logged-out tabs clobbered each other's `nc_oauth_state` cookie —
   sidebar now ADOPTS an existing cookie value before minting.
8. `credits=0` filter counted as "active" but never sent (`fv not in
   (None, "", 0)`); 0-credit courses are legal.
9. Co-op form: empty required fields surfaced a raw pydantic list with the
   irrelevant k-anonymity hint; client-side check + hint now conditional
   on the actual k-anonymity message.
10. Successful co-op upload didn't refresh the listing/sidebar count —
    now bumps count + `st.rerun()` (success message survives via state).
11. `RequestValidationError` bypassed the ErrorResponse contract (detail
    was a list of dicts); handler added, detail flattened.
12. 500s lacked the `x-request-id` their own body referenced (handler runs
    outside `RequestLogMiddleware`); recovered from structlog contextvars.
13. POST /coop with a valid token for a deleted user → FK 500; now 401
    ("Unknown user"), same contract as /auth/me.
14. `FUSION_WEIGHT`/`FUSION_MODE`/`REJECTION_MODE` unvalidated — env typo
    silently reverted prod ranking or 500'd per-request. Now `Literal` +
    bounded `Field` ⇒ loud boot failure.
15. Dockerfile's out-of-lock `optimum`/`optimum-intel` drift risk —
    **fix attempt itself caused an outage** (see Verification): the
    review agent recommended pinning `<2` because "optimum 2.x broke the
    PC", but the PC incident was the optimum-onnx EXPORT path; production
    INFERENCE has been running optimum 2.x all along. The `<2` pin
    downgraded to an optimum 1.x that imports `_attention_scale` from
    torch.onnx — removed in torch 2.12 — and the api crash-looped at
    boot. Reverted to unbounded; known-good versions recorded in the
    Dockerfile comment (optimum 2.2.0 / optimum-intel 2.0.0 /
    torch 2.12.0+cpu / transformers 4.57.6) for exact pinning if a future
    rebuild breaks. Lesson: verify an agent's claimed incompatibility
    against what production ACTUALLY runs before acting on it.
16. No `HF_HOME` in compose — every api container recreation re-downloaded
    tokenizers from the hub and hard-failed offline. Now `/data/.hf_cache`.

### LOW

17. Search route: all-dangling alias returned `matched_via=alias` with
    `[]` instead of falling through to hybrid (chat already fell through).
18. Alias tier ignored explicit request filters — filtered requests now
    bypass the (filter-blind) alias shortcut in both routes.
19. HyDE-rescued requests logged as plain `hybrid` — telemetry now writes
    `matched_via=hyde_rescued` (response unchanged) so ADR-0019 rescue
    rate is minable from query_log.
20. Router-level 404/405 (starlette `HTTPException`) bypassed the error
    contract — handler re-registered against the starlette class.
21. Google's deny redirect (`?error=access_denied`) was silently ignored.
22. Standalone co-op page never flushed/restored the session cookie.
23. Glossary loader accepted non-string senses (one bad regeneration =
    `AttributeError` on every non-alias request) — per-entry type check.
24. `attempt_hyde_rescue`'s try-scope covered only the LLM call; the retry
    retrieval/rerank could 500 a request that had a valid rejected
    response. Whole rescue now guarded.
25. UI container had no healthcheck and cloudflared routed on
    `service_started` — public 502s right after each deploy. Added
    `/_stcore/health` check; cloudflared now waits for healthy.

## Accepted (not fixed, on purpose)

- **X-Eval-Run is spoofable** on the public API. Spoofing only REMOVES
  rows from the organic set (attacker hides); it cannot pollute organic.
  Single-maintainer product — a shared secret isn't worth the ops cost.
- **query_log grows unbounded** (≤500 chars/row, public endpoint).
  Revisit with a retention job if organic volume materializes.
- **deploy.ps1 tar doesn't propagate deletions** — documented; automatic
  remote deletes are riskier than the stale-file problem at this scale.

## Verification

- Tests 864 → **873**, all passing (new: field-redaction contract,
  deleted-user 401, validation/404/405/request-id error contract,
  transport-error wrapping, stream degradation, filter-bypass-alias,
  glossary type-check).
- Both containers: 65-module import sweep clean.
- Live API edge battery: 14/14 expected (422 validation incl. extra
  fields, rejection, filters, 404, coop auth tiers, auth/callback 401,
  chat NDJSON always ends with `done`).
- Live post-deploy: /coop anonymous returns all 30 rows with salary +
  interview stripped server-side (UI shows 60 🔒 unlock hints); 422/404
  error contract live; alias unfiltered still 0-ms; alias+credits=4 on
  "CS 5800" now honors the filter (rejected — prod row has NULL credits;
  data-quality note, not a logic bug); ui container reports healthy via
  the new healthcheck.
- Dead-button fix verified in a real browser: clicking result #2
  immediately after the stream finishes now switches the detail panel
  (previously silently dropped).
- Full v0.4 eval post-deploy: **R@5 0.8647 (= baseline) / MRR 0.9293
  (baseline 0.9357, Δ0.006 = HyDE-rescue LLM noise on 1-2 queries) /
  p50 857.7 ms**. No retrieval-path semantics changed for unfiltered
  queries, as expected.

## Method note

The agent split that worked: one reviewer per *failure domain* (UI
runtime, API contracts, packaging/config drift, RAG glue), each primed
with the day's bug pattern ("production path never exercised") and
forbidden from style nits. Dynamic checks (imports inside the real
containers, live endpoint battery, real click-through) caught the two
things static review couldn't see: the empty /coop marketplace and the
double-rendered panel.
