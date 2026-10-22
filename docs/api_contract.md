# NEU-Compass API contract (v0.1)

> **Audience**: frontend developers (Andy Dong's `compass-frontend`) and
> integration smoke testers. Backend-as-a-Service contract per PLAN v2.2 §3.3.
>
> **Source of truth**: this doc + `GET /openapi.json` on the live server. If
> they disagree, OpenAPI wins (it's generated from code).
>
> **Base URL** (Week 7 deploy — Cloudflare Tunnel split-subdomain):
> - Local dev: `http://localhost:8000`
> - **Public API** (canonical, what frontend hits): `https://api.neu-compass.me`
> - **Streamlit debug + OAuth callback landing**: `https://compass.neu-compass.me`
>
> Both subdomains are CNAMEs to the same `neu-compass` tunnel (UUID
> `ce52553f-7fc3-…`). FastAPI lives at root path on `api.*`, no `/api`
> prefix needed; the path-prefix design from earlier drafts was dropped
> because cloudflared can't strip prefixes natively. See
> `docs/cloudflare_tunnel.md` §11 for the full deploy walkthrough.
>
> **Tech**: FastAPI + Pydantic v2 (`extra='forbid'` on every input model — typo'd
> fields fail loud with HTTP 422, never silently). Auth in Week 6 is the
> `Authorization: Bearer <session_token>` (ADR-0021) — token issued by `POST /auth/callback`.

---

## Endpoint summary

| Method | Path                  | Purpose                                |
|--------|-----------------------|----------------------------------------|
| GET    | `/health`             | Process liveness                       |
| GET    | `/ready`              | Lifespan readiness (models warmed)     |
| POST   | `/search`             | Course search (alias→hybrid→rerank)    |
| GET    | `/course/{course_id}` | Full Course detail                     |
| POST   | `/coop`               | Submit Co-op (k=2 anonymity gated)     |
| GET    | `/coop`               | List Co-op visible to user             |
| POST   | `/chat`               | Streamed grounded chat (NDJSON)        |
| POST   | `/auth/callback`      | OAuth code exchange                    |
| POST   | `/auth/delete-account`| Delete own account + Co-op (batch T)   |

Auth model: anonymous for `/health`, `/ready`, `/search`, `/course/{id}`,
`/chat`, and `GET /coop` (degraded view). `POST /coop` and `POST /auth/delete-account` require
`Authorization: Bearer <session_token>`.
`POST /auth/callback` issues identity but takes no header itself.

---

## GET /health

Process liveness; no state inspection.

```bash
curl -s https://compass.<zone>.com/api/health
```

```json
{ "status": "ok" }
```

Always 200 if the process is up. Use for docker / systemd / Cloudflare basic
healthcheck. Use `/ready` to gate user traffic.

---

## GET /ready

Returns once the lifespan startup hook finished: FAISS loaded, BM25 corpus
built, **and both models warmed** (bge-m3 ~70s, bge-reranker-v2-m3 ~30s).

```bash
curl -s https://compass.<zone>.com/api/ready
```

```json
{
  "status": "ready",
  "courses_indexed": 6469,
  "bm25_corpus": 6469
}
```

While warming (typical 70-100s after process start):

```json
{
  "status": "warming",
  "courses_indexed": 0,
  "bm25_corpus": 0
}
```

Orchestrators / Cloudflare LB should wait for `status='ready'` before sending
real traffic. The first user request after a cold start otherwise hangs ~70s.

---

## POST /search

Production search: alias-first short-circuit, then hybrid retrieval (BM25 +
bge-m3 RRF), then rerank+blend+reject (PLAN v2.2 §3.4 + §3.5, ADR-0015 + 0016).

### Request

```bash
curl -s -X POST https://compass.<zone>.com/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "graph algorithms BFS shortest paths",
    "k": 5,
    "term": "Spring 2026",
    "credits": 4,
    "delivery_mode": "in_person",
    "professor": null
  }'
```

| Field          | Type             | Required | Notes                                      |
|----------------|------------------|----------|--------------------------------------------|
| `query`        | string           | yes      | 1–500 chars                                |
| `k`            | int              | no       | 1–50, default 10                           |
| `term`         | string \| null   | no       | e.g. `"Spring 2026"`                       |
| `credits`      | int \| null      | no       | 0–12                                       |
| `delivery_mode`| string \| null   | no       | one of `in_person` / `online` / `hybrid`   |
| `professor`    | string \| null   | no       | substring filter                           |

`delivery_mode` validation: any other string returns 422 (e.g. `"telepathy"`).
Filters combine with AND; nulls are dropped.

### Response shapes

**Alias hit** (`matched_via='alias'`):

```json
{
  "query": "CS 5800",
  "k": 5,
  "matched_via": "alias",
  "results": [
    {
      "course_id": "neu-cs-5800",
      "primary_code": "CS 5800",
      "primary_name": "Algorithms",
      "score": 1.0,
      "matched_via": "alias"
    }
  ],
  "latency_ms": 3.21,
  "rejection_reason": null
}
```

**Hybrid hit** (`matched_via='hybrid'`):

```json
{
  "query": "graph algorithms BFS shortest paths",
  "k": 5,
  "matched_via": "hybrid",
  "results": [
    {
      "course_id": "neu-cs-5800",
      "primary_code": "CS 5800",
      "primary_name": "Algorithms",
      "score": 1.42,
      "matched_via": "hybrid"
    }
  ],
  "latency_ms": 47.8,
  "rejection_reason": null
}
```

> Note: `score` here is the **blended Z-score** (typically -2 to +2, centered
> on 0). It's a relative ranking signal, NOT a [0,1] confidence. The alias
> path returns 1.0 as a sentinel.

**Rejected** (`matched_via='rejected'`):

```json
{
  "query": "ancient roman empire",
  "k": 5,
  "matched_via": "rejected",
  "results": [],
  "latency_ms": 49.6,
  "rejection_reason": "max_reranker_sigmoid 0.012 < threshold 0.05"
}
```

Triggered when `max(raw bge-reranker sigmoid) < 0.05`. Frontend should render
a "no good match — try rewording" affordance, not the empty-list state.

**Empty** (`matched_via='empty'`):

```json
{
  "query": "neural network",
  "k": 5,
  "matched_via": "empty",
  "results": [],
  "latency_ms": 2.4,
  "rejection_reason": null
}
```

Hybrid retrieval returned zero candidates (filter dropped everything).
Distinct from `rejected` — no reranker pass happened.

### Error responses

- **422** on validation failure (empty query, k out of range, unknown
  `delivery_mode`, extra fields like `kk` instead of `k`).

---

## GET /course/{course_id}

Full Pydantic Course (schema v1.1 — see `schemas/course.py`). Includes soft
fields with their `evidence_snippets` when present.

```bash
curl -s https://compass.<zone>.com/api/course/neu-cs-5800
```

Response is the dumped Course model. Selected fields (full list in
`schemas/course.py`):

```json
{
  "course_id": "neu-cs-5800",
  "primary_code": "CS 5800",
  "primary_name": "Algorithms",
  "term": "Spring 2026",
  "credits": 4,
  "delivery_mode": "in_person",
  "professor": "...",
  "raw_text": "...",
  "workload_hours_per_week": 12,
  "difficulty_score": 4.2,
  "skill_tags": ["algorithms", "data structures"],
  "career_relevance": ["software engineer", "quant"],
  "controversial_signals": [],
  "evidence_snippets": [
    {
      "field": "workload_hours_per_week",
      "source": "RMP review",
      "quote": "Expect 12-15 hours weekly..."
    }
  ],
  "schema_version": "1.1",
  "status": "indexed"
}
```

Soft fields are empty `[]` / `null` for synthetic seed courses. Co-op data is
NOT mixed in here — call `GET /coop?course_id=...` separately.

### Error responses

- **404** when `course_id` isn't in the `courses` table.

---

## POST /coop

Submit a Co-op experience. Server-side k=2 anonymity gate + content-driven
visibility tier.

### Request

```bash
curl -s -X POST https://compass.<zone>.com/api/coop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <session_token>" \
  -d '{
    "company": "Two Sigma",
    "role": "Quant Research Intern",
    "coop_term": "Summer 2025",
    "industry": "quant_fintech",
    "duration_months": 4,
    "related_courses": ["neu-cs-5800", "neu-aai-6600"],
    "interview_summary": "3 rounds: phone screen, ...",
    "technical_questions": "LeetCode medium DP, ...",
    "salary_range_usd": "$8k-12k/month"
  }'
```

| Field                | Type     | Required | Notes                              |
|----------------------|----------|----------|------------------------------------|
| `company`            | string   | yes      | 1+ chars                           |
| `role`               | string   | yes      | 1+ chars                           |
| `coop_term`          | string   | no       | e.g. `"Spring 2025"`               |
| `industry`           | enum     | no       | `quant_fintech` / `big_tech` / etc |
| `duration_months`    | int      | no       | 1–8                                |
| `related_courses`    | list[str]| no       | course_ids (default `[]`)          |
| `interview_summary`  | string   | no       | ≤10000 chars                       |
| `technical_questions`| string   | no       | ≤10000 chars                       |
| `salary_range_usd`   | string   | no       | free-form ("$8k/mo")               |

`Authorization: Bearer <session_token>` is required (ADR-0021; minted by `POST /auth/callback`).

### Server-side derivations (NOT client-controllable)

- `visibility_level`:
  - `2` if `salary_range_usd` present
  - `1` if `interview_summary` or `technical_questions` present
  - `0` otherwise
- `coop_id`: server-generated UUID (`coop-<12 hex>`)
- `contributor_user_id`: resolved server-side from the verified session token
- `is_seed_data`: always `false` for client uploads (true only for the
  curated Co-op Seed Data, see PLAN §6.5)

### Success (HTTP 201)

```json
{
  "coop_id": "coop-a1b2c3d4e5f6",
  "accepted": true,
  "visibility_level": 2
}
```

### Error responses

- **401** when the session token is missing, invalid, or expired.
- **422** when:
  - the (company, role, coop_term) triple is uniquely identifying (k<2
    after insert) — response detail includes a generalization hint.
  - validation fails (extra fields, invalid `industry`, `duration_months`
    out of range, etc.)

---

## GET /coop

List visible Co-op records per the give-to-get gate (PLAN §6.4).

```bash
# Anonymous — only level-0 (preview) rows
curl -s https://compass.<zone>.com/api/coop

# Authenticated — tier proportional to user's contribution_count
curl -s https://compass.<zone>.com/api/coop \
  -H "Authorization: Bearer <session_token>"
```

Response is a list of `CoopOut`:

```json
[
  {
    "coop_id": "coop-a1b2c3d4e5f6",
    "company": "Two Sigma",
    "role": "Quant Research Intern",
    "industry": "quant_fintech",
    "coop_term": "Summer 2025",
    "duration_months": 4,
    "related_courses": ["neu-cs-5800", "neu-aai-6600"],
    "interview_summary": "...",
    "technical_questions": "...",
    "salary_range_usd": "$8k-12k/month",
    "visibility_level": 2
  }
]
```

The detail fields (`interview_summary`, `technical_questions`, `salary_range_usd`)
are NULL on rows the caller can't see. `contributor_user_id` and
`redaction_audit` are server-internal and never returned.

---

## POST /chat

Streamed grounded course advisor. Returns `application/x-ndjson`.

### Request

```bash
curl -N -X POST https://compass.<zone>.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what is a good first ML class for someone with Python but no calculus",
    "k": 5,
    "term": "Spring 2026"
  }'
```

Body shape mirrors `SearchRequest` minus the response constraints (k
default=5, max 20).

### Wire format

One JSON object per line. Order of object types:

1. **First line — meta**:
   ```json
   {"type": "meta", "matched_via": "hybrid", "retrieval_ms": 47.8, "results": [{"course_id":"neu-ds-5220","primary_code":"DS 5220","primary_name":"Supervised ML","score":0.62}]}
   ```
   Render evidence bubbles before tokens land.

2. **Zero or more — token**:
   ```json
   {"type": "token", "text": "DS 5220 "}
   {"type": "token", "text": "Supervised "}
   ```
   Concatenate `text` fields in order to reconstruct the assistant's reply.

3. **Optional — error** (stream failure):
   ```json
   {"type": "error", "error_type": "upstream_error", "detail": "模型服务暂时出错，这条回答没有完成。请稍后再问一次。"}
   ```
   `error_type` is one of:
   - `upstream_error`: the Gemini call or stream failed;
   - `no_answer`: Gemini returned no text (a safety block or an empty
     completion), so asking the same way again rarely helps;
   - `internal_error`: anything else;
   - `daily_limit` (batch T): today's Gemini calls are used up (`MODEL_DAILY_CALL_LIMIT`, per UTC day). It comes
     right after meta, instead of any token; retrieval still ran and the courses are in meta. No model call is made.

   `detail` is fixed text per `error_type` that the UI appends to the partial
   answer; it never carries the exception message, which can hold upstream URLs
   or request/response bodies. The server log line (`chat.stream_failed` /
   `chat.stream_unhandled`) carries the same `request_id` as the response's
   `x-request-id` header. It records only:
   - the exception types and the Gemini error kind;
   - the upstream HTTP status and status name (e.g. `RESOURCE_EXHAUSTED`);
   - how many token events had been sent;
   - for an unexpected error, where it was raised (file:line function).

4. **Always last — done**:
   ```json
   {"type": "done"}
   ```

> **No reranker on the chat path** in v0.1 — first-token latency is the UX
> currency, and the ~50ms blocking rerank cost would push it over budget.
> If retrieval recall becomes the chat bottleneck, revisit at v0.2.

### Error responses

- **422** on invalid request body. The error response is plain JSON, NOT
  NDJSON — the stream never starts.

---

## POST /auth/callback

Exchanges an OAuth `code` (returned by Google's redirect) for a verified
identity and persists the user row.

### Request

```bash
curl -s -X POST https://compass.<zone>.com/api/auth/callback \
  -H "Content-Type: application/json" \
  -d '{
    "code": "4/0AfJohXm...",
    "redirect_uri": "https://compass.<zone>.com/oauth/callback"
  }'
```

`redirect_uri` is optional; defaults to the value configured in
`config/settings.py` `oauth_redirect_uri`.

### Success (HTTP 200)

```json
{
  "user_id": "u-google-1234567890",
  "email": "alice@husky.neu.edu",
  "display_name": "Alice Husky",
  "contribution_count": 0
}
```

### Error responses

- **401** when:
  - code exchange fails at Google
  - the returned JWT signature/claims fail validation
  - the email domain isn't whitelisted (PLAN §3.5: split-on-`@` exact match
    for `husky.neu.edu` / `northeastern.edu`; `attacker@husky.neu.edu.evil.com`
    is rejected)

---

## POST /auth/delete-account

Batch T (10-21, policy P4): a logged-in student deletes their own account and Co-op contributions from the
数据与隐私 page. Needs `Authorization: Bearer <session_token>` and exactly `{"confirm": "delete"}`.

In one transaction (`db/account_deletion.py`):
1. the Co-op experiences this account published, and every unlock of them;
2. the `users` row, which cascades to its unlocks, planned courses, Co-op submissions (any review state) and
   contribution credits;
3. a group (company, role, term) this account helped publish that is left with only one contributor is withdrawn:
   the others' items go back to `approved` and leave the public list (with their unlocks) until another approval in
   the group publishes them again. Credits already given are kept, and none is given twice. The user chose this
   on 10-21 so that the last item cannot point at its author (k=2).

`query_log` and saved answers never record an account (a real user's `user_id` is NULL) and are not touched. Daily
backups keep a copy for up to 14 days. Afterwards the same token gets 401 from `GET /auth/me` and from this route.

### Success (HTTP 200)

```json
{"deleted": true, "published_experiences": 1, "unlocks_of_those": 0, "own_unlocks": 2,
 "submissions": 3, "credits": 1, "planned_courses": 0, "withdrawn_from_groups": 1}
```

Counts only; the log line `account.deleted` carries the same counts and no identity.

### Error responses

- **401**: missing, invalid or expired token, or the account no longer exists.
- **422**: the body is not exactly `{"confirm": "delete"}`.

---

## Conventions

- **All inputs**: `extra='forbid'` Pydantic config. Typo'd fields → 422 with
  a detail message naming only fields matching `[A-Za-z_][A-Za-z0-9_.]{0,63}`;
  other locations become `<field>`. Unknown keys are still rejected. Don't try to "be helpful" by accepting
  unknown keys.
- **Latency**: `latency_ms` is wall-clock from request entry to response
  encode. Doesn't include Cloudflare edge overhead.
- **Logging**: completed requests emit a `structlog` JSON line on stderr with
  `request.handled` + duration. Uncaught errors before response headers are sent emit
  one `request.unhandled` event and return the fixed 500 below, not a second traceback.
  Console mode also consumes exception information before rendering: no Rich locals.
  Route events never carry the question text: they log `query_hash` (a keyed HMAC) and `query_len` (the two
  `prefilter_applied` events log `sanitized_query_hash` and `sanitized_query_len` for the question without its
  program prefix), and `query_log.written` logs the `query_log` row id. See [PII 脱敏指南 §11](pii_redaction.md).
- **Versioning**: this is v0.1. Breaking changes go in v0.2 with a
  parallel `/v2/*` prefix; never silent breaks.

### Safe error exits (SAFE-02)

The `{detail, error_type, status_code}` shape and existing HTTP status codes remain.
Uncaught 500 uses `internal_error`; other HTTP 5xx use `server_error` unless explicitly
mapped (502 `upstream_error`, 503 `service_unavailable`); 429 is `rate_limited`.
No request ID is added to the body. An inbound `x-request-id` is retained only if it
matches `[A-Za-z0-9._-]{1,64}`, otherwise a UUID4 replaces it in the response header
and request log context.

- Uncaught 500 detail: `Internal server error. Check API logs by x-request-id.`
- Course/program missing: `Course not found` / `program_id not found`, without the
  supplied path ID. Invalid delivery mode: `Invalid delivery_mode`, without the value.
- OAuth refusal remains 401, including Google network errors. Fixed text is selected
  from seven reasons: `token_exchange_rejected`, `token_endpoint_unreachable`,
  `missing_id_token`, `id_token_invalid`, `claims_invalid`, `email_unverified`,
  `domain_not_allowed`. Google descriptions, tokens and email addresses are not returned.
  Status changes: malformed Google responses that used to raise an uncaught 500 are now
  this 401 — a 200 body that is not JSON or not a JSON object, a 4xx JSON body that is not
  an object, and a non-string email claim.
- Chat 409 still offers database-backed program IDs and selection guidance, but no
  appended exception text. The existing Gemini 502 and chat stream error contracts remain.

Safe error diagnostics allow request_id, method, path, status, duration_ms; error_type,
exc_type, cause_type, error_kind, upstream_status, upstream_reason; frames, tokens_sent,
oauth_reason, google_error, email_domain; and existing database coop_id/program_id/course_id.
Frames are at most six `file.py:LINE function` entries (basenames, no source or locals).
Cause type falls back to implicit exception context, except Starlette's re-raise
artefacts: the `anyio.EndOfStream` that `BaseHTTPMiddleware` leaves on a cause-less
error, and the exception group around the error after headers are sent. Google error codes match
`[a-z_]{1,64}`; refused domains are lowercase and match `[a-z0-9.-]{1,253}`.
No exception str/repr, traceback text, error_description, email, OAuth code, session/
feedback token, headers or body content is logged in these diagnostics. Foreign stdlib
messages routed through the configured root handler are replaced by fixed `stdlib.log` /
`stdlib.error` events with safe diagnostics; level, the code-defined logger name, a
timestamp and request context remain. Successful project events retain their existing fields.

The UI client uses fixed text for 5xx and non-JSON error bodies, retaining status and safe
error_type; malformed 2xx JSON becomes `ApiError(502, error_type="invalid_response")`.
The existing fixed invalid-response notice is preserved, as are rate/busy/timeout notices.
Malformed identity shapes (OAuth callback and cookie restore) fail without modifying
login state; a malformed restore keeps the cookie, like an outage. Streamlit defaults to
`client.showErrorDetails="type"`; full details are opt-in for local development only.

Boundaries: this does not remove successful query text logs or query_log contents, or
potential sensitive data in request paths/access query strings. (The Google sub that
`auth.callback.success` used to carry was dropped in batch T: the line keeps only the
domain and the contribution count.) Exceptions after response headers are sent cannot be converted to this
500 body: they are logged once as a safe `unhandled_exception`, but uvicorn's own
`Exception in ASGI application` traceback (its handler bypasses the root filter) still
prints the message. `/chat` builds its first (meta) line before the response starts and
turns model-stream errors into stream error events, so no production path is known to
reach this. Python `warnings` and the Streamlit process log (uncaught UI exceptions) also
print full text; the browser shows the exception type only. No general PII-free logging
claim is made.

## Frontend touch-points (for Andy)

When the contract above is unambiguous, here are the recommended bindings:

| UI affordance              | Endpoint                | Notes                                |
|----------------------------|-------------------------|--------------------------------------|
| Search box                 | `POST /search`          | k=10 default                         |
| "Show more like this"      | `POST /search` again    | mutate query, no in-page filter      |
| Course detail panel        | `GET /course/{id}`      | navigation from any hit              |
| Evidence bubble click      | (read from `/course`)   | source quote + field is in `evidence_snippets` |
| Co-op tab on course page   | `GET /coop?…`           | tier-aware; degraded for anonymous   |
| Submit Co-op modal         | `POST /coop`            | requires Bearer session token (ADR-0021)   |
| "Ask the advisor" chat     | `POST /chat`            | NDJSON; render meta first, then stream tokens |
| Login button               | redirect → Google OAuth | callback → `POST /auth/callback`     |
| Rejected search affordance | `matched_via='rejected'`| show `rejection_reason` + reword CTA |

If the contract is missing something you need (e.g. a faceted filter list, a
"saved searches" endpoint), file an issue against `compass-frontend` and
we'll evaluate post-Week-7. Don't extend the contract by stuffing fields into
the URL — additive endpoints only.
