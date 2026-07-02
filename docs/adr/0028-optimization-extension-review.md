# ADR-0028: Optimization & extension review — quick wins landed, roadmap ranked

Date: 2026-06-13
Status: Accepted (code landed; NAS deploy + measurements pending — NAS was
offline during this round, which itself proved the backup finding)

## Context

After the bug sweep (ADR-0026) and continuity/frontend round (ADR-0027),
a second full review ran with an optimization/extension lens: four
parallel agents (performance / product extensions / data quality &
enrichment / architecture & debt) + local measurements. Mid-review the
NAS dropped offline (public 530) — a live demonstration of the review's
own top operational finding: the production DB has no backup.

## Landed this round (all tested, 918 → 923)

**Performance**
1. Unconditional `filter_ids` full-table SELECT removed from
   `Retriever.search_ids` — every unfiltered search fetched ~6.5k ids and
   threw them away (~5-15ms free).
2. Single-query embedding LRU (256 entries) in `OvEmbedder.encode` — the
   UI's fixed sample/follow-up chips guarantee verbatim repeats; hits
   skip the ~50-100ms Iris Xe forward. Batch (indexing) calls bypass it.
3. HyDE rescue Gemini call now carries an 8s HTTP budget (was the 120s
   client default — one slow Gemini response could pin a threadpool
   worker and the user for two minutes inside /search).
4. `RERANKER_MAX_LENGTH` setting (default 512, env-overridable) + a
   DEBUG padded-seq-len log in `OvReranker.score`. The June optimization
   doc predicted 1.5-2x on the rerank pass (≈70% of p50) at 256; the A/B
   (measure padded lens → set 256 → eval) runs when the NAS is back.

**Data quality**
5. `scripts/backfill_prereq_edges.py` — converts catalog-scraped prereq
   CODES (already clean, whole catalog) into course_prerequisites edges.
   Local run: **35 → 5,823 edges (2,509 courses)**, 10 dangling codes
   skipped, seeded program edges untouched (INSERT OR NOTHING). Turns the
   detail-panel prereq graph from a 4-program demo into a catalog-wide
   feature. NAS run pending.
6. Enrichment clobber fixed: `enrich_course` now MERGES only
   `ENRICHMENT_FIELDS` (soft fields + evidence) onto the incoming Course
   — the old return-LLM-object-wholesale nulled catalog facts the LLM
   never saw (CS 5800 lost `credits` exactly this way; repair of the ~3
   damaged rows pending NAS).
7. Dead filters hidden in the UI: term / delivery_mode (0/6,469 coverage
   — no pipeline populates them) and professor (~3 courses) removed from
   Advanced filters; only credits (catalog-wide) remains. Each returns
   when a real pipeline feeds it.
8. Soft-field rendering in the course detail panel (workload, difficulty,
   grading components, skill tags, career relevance) + friendly ai_policy
   rendering (was a raw st.json dump). Coverage is ~3 courses today but
   the surface must exist before enrichment scales.

**Ops / debt**
9. `deploy.ps1 -SyncData` now excludes `courses.db` — it previously would
   have silently REPLACED production users/coop/query_log with the dev
   copy. Also: pre-flight now checks writability (UGOS reboot chown
   issue) and prints the fix command.
10. `scripts/nas_backup.sh` — daily SQLite Online-Backup snapshot via the
    api container, 14-day retention. Needs one-time UGOS Task Scheduler
    registration (pending NAS).
11. Bounded container logs (10MB × 3) on all three services — default
    json-file driver grows unbounded on a 24/7 NAS.
12. Dependency/debt prune: playwright + deepeval removed (imported by
    nothing), dead Settings fields removed (embedding_dim,
    api_budget_alarm), reddit creds no longer required in prod .env
    (scraper-only), chat_v1 prompt deleted.

## Ranked roadmap (not landed — the extension backlog)

**Do before distributing** (from the product review)
- **Deep links** (`?course=CS-5800`, `?program=cs-ms`): the organic-spread
  mechanism itself. Params consumed in the same pre-radio block as the
  pending_nav flags; carry the human code and resolve via the alias tier.
  Watch out: `handle_oauth_callback` calls `st.query_params.clear()`.

**First post-launch**
- **Answer feedback 👍/👎**: log_query returns lastrowid → meta event
  carries log_id → `POST /feedback` + two buttons next to the follow-up
  chips. Turns organic traffic into LABELED eval pairs for v0.5.
- **Semester planner**: pure ontology logic (taken-courses multiselect →
  prereq-satisfied next-semester suggestions). The `user_courses` table
  DDL already exists (schema v1.1) for later persistence.
- **RMP enrichment of the top-N organic-queried courses** (~$0.05/course,
  drive the list from query_log once real traffic exists; re-verify the
  RMP GraphQL schema first — probed 2026-05-03).

**Performance follow-ups (measure-first, on the NAS)**
- RERANKER_MAX_LENGTH=256 A/B (expected p50 852 → ~550-650ms if pools
  actually pad near 512; the new DEBUG log answers that first).
- Static-shape reshape (10, 256) compile — benchmark AFTER 256 lands;
  each changes the other's payoff.
- `return_tensors="np"` to drop CPU torch from the image (~200MB image,
  RSS win) — needs optimum-intel 2.0.0 verification on the NAS.
- BM25 corpus pickle cache keyed on (count, max updated_at) — only if
  startup logs show it matters (~1-4s estimate).

**Data follow-ups**
- Repair credits on the ~3 enrichment-clobbered rows (catalog JSONL or
  re-fetch) — NAS.
- Fresh catalog re-scrape (2 months stale; also fix `_TITLE_RE` to accept
  credit RANGES — "1-4 Hours" courses are silently dropped today) →
  rebuild_faiss + mark_pending_indexed + doc2query delta.
- Bare-number aliases ("5800" → CS 5800; collisions resolve as lists) and
  primary_name in v_course_lookup (exact-title lookup) — both zero-LLM.
- doc2query staleness guard (compare artifact vs courses.updated_at).
- Syllabus pipeline is the ONLY identified source for term / meeting
  schedule / ai_policy at scale — consider give-to-get syllabus uploads.

**Deliberately rejected**
- Image split for the UI container: the UI imports nothing heavy (only
  rag.prereq_graph, a pure string builder); one shared image is
  disk-neutral and operationally simpler.
- /chat "send meta earlier / start Gemini during rerank": meta content
  requires final reranked hits; restructuring changes semantics. The real
  first-token lever is the rerank latency itself.
- API URL versioning, docs_url hardening: single-client MVP, ceremony
  without benefit today.

## NAS recovery + execution log (2026-07-02, all done)

The "NAS offline" turned out to be a **UGOS Docker-package update** that
(a) re-applied volume ACLs denying non-root reads under /volume1/docker
and (b) stopped containers in a way `unless-stopped` doesn't recover
from. cloudflared (runs as uid 65532) could no longer read its tunnel
credentials → crash loop → public 530; the tailscale container's boot
`tailscale up` refused to run because persisted non-default flags
(--accept-dns=false --advertise-exit-node) weren't re-stated. api/ui
kept running the whole time (LAN was fine).

Fixes, all encoded in compose now: cloudflared runs as `user: "0"`,
tunnel by UUID (name resolution needed cert.pem + an API round-trip
every cold start), image digest-pinned; ALL services `restart: always`;
tailscale container rebuilt with TS_EXTRA_ARGS carrying its flags.
Root-owned residue (.deepeval, .streamlit ACLs) cleared via
container-root chown — the same trick now documented for the UGOS
reboot case (no sudo needed).

Checklist execution:
1. ✅ Deployed (after container-root `chown -R 1000:10 /target`).
2. ✅ `backfill_prereq_edges.py --commit` on prod: **35 → 5,823 edges**
   (2,509 courses). Credits repaired from the catalog JSONL:
   CS 5800=4, CS 5200=4, AAI 6600=3 (all were NULL).
3. ✅ First backup snapshot taken (15MB; script needed `docker exec -i`).
   UGOS has no user crontab — **daily registration must be done once in
   UGOS Task Scheduler GUI** (user action):
   `sh /volume1/docker/neu-compass/scripts/nas_backup.sh`.
4. ✅ cloudflared digest-pinned in compose.
5. ✅ **RERANKER 256 A/B: REJECTED by measurement.** Prod-corpus probe:
   pair token lengths p50=110 / p99=206 / max=239, 0% above 256. The
   tokenizer uses DYNAMIC padding (to batch max, not to max_length), so
   the rerank pass already runs at ~110-240 tokens — 512→256 changes
   nothing (the perf agent's padding assumption was wrong). The real
   next lever is static-shape compile at (pool, 256), which the probe
   now justifies sizing. RERANKER_MAX_LENGTH setting stays (useful for
   that experiment).
6. Prod field-coverage measurement folded into the data findings above.

**Rescue-timeout incident (caught by the post-deploy eval):** the 8s
Gemini budget was REJECTED by the API itself ("Minimum allowed deadline
is 10s", 400) — every rescue died instantly, R@5 dropped 1.25pts
(q013/q018, the flagship borderline-rescue queries, went to 0). Fixed at
12s; final eval **R@5 0.8628 / MRR 0.9293 / rejected 10 / p50 851ms** =
baseline. Two lessons re-learned in one evening: measure before
optimizing (256), and re-run eval after ANY hot-path change, even a
"safe" timeout (8s).
