// Generated from openapi.json by `npm run gen:api` (openapi-typescript). Do not edit by hand:
// change the API, run `python scripts/export_openapi.py` from the repository root, then `npm run gen:api`.

export interface paths {
  '/auth/callback': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Google OAuth code → JWT verify → user upsert
     * @description Exchanges the OAuth `code` (returned by Google's redirect) for an ID token, verifies the JWT signature + claims, and upserts the user row. Returns the sanitized identity for client-side session state.
     *
     *     **Domain whitelist** is enforced inside JWT-claim validation — non-NEU emails get 401 (PLAN §3.5: split-on-`@` exact match, NOT substring; `attacker@husky.neu.edu.evil.com` is rejected).
     *
     *     **F1 compliance**: no payment surface, no commercialization. The Google client must be set up under the developer's personal Google Cloud project — credentials never enter version control.
     *
     *     **Session** (R2a): `"session": "token"` (the default) returns the signed token as `session_token`, as before. `"session": "cookie"` sets it instead as the HttpOnly cookie `__Host-nc_api_session` (Secure, Path=/, SameSite=Lax, as long as the token lasts) and returns `session_token: null`; the web front end uses this. The cookie mode must come from an allowed web origin with `X-NEU-Compass: 1`, or it gets the fixed CSRF 403 before the code is exchanged: a page elsewhere must not log the browser into an account of its choosing.
     *
     *     **redirect_uri** (R2b): the address Google sent the browser back to, which Google checks again in the exchange; it defaults to `GOOGLE_OAUTH_REDIRECT_URI`. The cookie mode takes only the front end's own address, the request's `Origin` (one in `WEB_ORIGINS`) followed by `/`, and answers 422 to anything else before the code is exchanged.
     */
    post: operations['oauth_callback_auth_callback_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/auth/delete-account': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Delete the caller's account and Co-op contributions (batch T)
     * @description Requires `Authorization: Bearer <session_token>` (or the API's session cookie, R2a) and the body `{"confirm": "delete"}`. In one transaction removes the Co-op experiences this account published (and every unlock of them); then a group it helped publish that is left with one contributor goes back to approved (k=2; no credit is taken back); then the users row, which cascades to its unlocks, planned courses, Co-op submissions and credits. query_log and saved answers never record an account and are not touched; daily backups keep a copy for up to 14 days. Afterwards the same token gets 401 from `/auth/me`. A session cookie used for the call is expired, and so is one that no longer works (with the 401). Returns per-table counts only.
     */
    post: operations['delete_account_auth_delete_account_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/auth/login-url': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Google's login address for the web front end (R2a)
     * @description Builds the Google OAuth address with the caller's `state`, exactly as the Streamlit login link does (`api.google_oauth.authorize_url`). The front end makes `state`, keeps it, and checks it when Google sends the browser back with `?code=&state=`; then it posts the code to `/auth/callback` with `"session": "cookie"` and the same `redirect_uri`. Google sends the browser back to `redirect_uri`, which must be a web front end's own address, an origin in `WEB_ORIGINS` followed by `/` (R2b); without it, to `GOOGLE_OAUTH_REDIRECT_URI`. The API stores nothing here.
     */
    get: operations['login_url_auth_login_url_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/auth/logout': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Expire the session cookie (R2a)
     * @description Expires the API's session cookie and answers 204, also when there is none. Bearer tokens are not revoked (they expire on their own; Streamlit logs out by dropping its copy). It must come from an allowed web origin with `X-NEU-Compass: 1`, with or without the cookie, or it gets the fixed CSRF 403 and expires nothing: a page elsewhere must not log the browser out.
     */
    post: operations['logout_auth_logout_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/auth/me': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Identity behind the Bearer session token or the session cookie
     * @description Verifies the `Authorization: Bearer <session_token>` credential and returns the current identity from the users table. The UI calls this on page load to restore login state from a persisted cookie — the token signature + max-age are re-checked server-side on every call, so a stale or tampered cookie degrades to 401, never a forged identity.
     *
     *     Without an Authorization header, the API's own session cookie (`__Host-nc_api_session`, set by the cookie mode of `/auth/callback`) is used instead. When that cookie no longer works (bad, expired, or its account is gone), the 401 also expires it.
     */
    get: operations['auth_me_auth_me_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/chat': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Streamed grounded course advisor (NDJSON)
     * @description Streams a Gemini-generated answer grounded in the retrieved courses.
     *
     *     **Wire format**: `application/x-ndjson` — one JSON object per newline. Object types in order:
     *
     *     1. `{"type": "meta", "matched_via": "alias|hybrid|empty", "retrieval_ms": float, "results": [{course_id, primary_code, primary_name, score, answer_evidence}, ...], prompt_version, notices?}` — emitted first so the client can render evidence bubbles before tokens land. `notices` appears only when non-empty, e.g. `program_schedule_unverified`: a first-semester/foundational question for a family whose version-scoped rules carry no verified schedule was answered from hybrid retrieval instead of a guessed sequence.
     *     2. `{"type": "token", "text": "..."}` — zero or more, Gemini stream chunks.
     *     3. `{"type": "error", "error_type": "upstream_error|no_answer|internal_error|daily_limit", "detail": "..."}` — only on stream failure, or `daily_limit` instead of tokens when today's model calls are used up (`MODEL_DAILY_CALL_LIMIT`). `detail` is fixed text, never the exception; the server log line carries the same `x-request-id`.
     *     4. `{"type": "done", "feedback": {answer_id, answer_sha256, feedback_token}}` — always last; feedback is optional and issued only after a complete, non-empty answer and successful private storage. Never in meta. Receipt authorizes only this answer's latest vote via `POST /feedback`.
     *
     *     Context, exact aliases, and program shortcuts apply explicit filters before top-k. Hybrid candidates use the same reranker/rejection policy as `/search`, including queries with a program prefix. Answer evidence distinguishes archived catalog snapshots, extracted field quotes, unverified provenance and explicit data gaps; it is not a live catalog verification.
     */
    post: operations['chat_chat_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/config': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What the web front end needs to know about this API (R2a)
     * @description `answer_feedback_enabled`: whether to show the opt-in and the votes. `login_available`: Google's client ID and secret and a SESSION_SECRET are all configured, so `/auth/login-url` and the cookie login work (the same condition as login-url's 503).
     */
    get: operations['public_config_config_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/coop': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Co-op records (give-to-get, field-level redaction)
     * @description Returns curated seeds and reviewed UGC with at least two distinct contributors; applies tier-gated FIELD redaction server-side (PLAN §6.4):
     *
     *     - tier 0 (anonymous / no contributions): company, role, term, industry, duration visible; interview/technical/salary `null`.
     *     - tier 1 (contribution_count ≥ 1): + `interview_summary`, `technical_questions`.
     *     - tier 2 (contribution_count ≥ 2): + `salary_range_usd`.
     *
     *     `visibility_level` reports the row's intrinsic tier (from content presence), so clients can render 'contribute to unlock' hints for redacted fields.
     *
     *     Each row is sanitized: `contributor_user_id` and `redaction_audit` are server-internal and NOT returned.
     *
     *     Before the v1.3 moderation migration the list degrades to curated seeds (public browsing never 503s); the `X-Coop-Moderation` header reports `available` or `missing` so deploy checks can still detect an unapplied migration. Uploads still require the schema.
     */
    get: operations['list_coop_coop_get'];
    put?: never;
    /**
     * Collect a private Co-op submission for review
     * @description Authenticated uploads are accepted into a PRIVATE pending queue, not published. A curator must supply reviewed/redacted content; publication requires at least two distinct authenticated contributors with the same company/role/term. Seeds and repeat submissions cannot establish this threshold. Contribution credit is awarded only once per contributor/reviewed group at publication. Retries return the existing submission without replacing its content. 'accepted' means stored, NOT publicly visible; 'status' reports the review state. visibility_level is content-derived; contributor identity comes from a signed Bearer session.
     */
    post: operations['upload_coop_coop_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/course/{course_id}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get full Course detail (+ program context)
     * @description Returns the rehydrated Pydantic Course (schema v1.1, see `schemas/course.py`). Includes soft fields (workload, difficulty, skill_tags, career_relevance, controversial_signals) **with their evidence_snippets** when present — the UI's evidence-bubble component uses these for source-quote display.
     *
     *     Additionally resolves the Layer 3 ontology context: `program_context` (programs whose curriculum lists this course) and `prerequisites` (prereq edges with display names). Both are `[]` for courses outside any seeded program.
     *
     *     Co-op data is **not** mixed in; call `GET /coop?course_id=...` separately so visibility-tier authorization stays in one place. `answer_evidence` adds recorded catalog provenance, extracted field quotes, missing fields and source/seed warnings; no raw_text is automatically labeled official. `course_requisites` lists year-scoped clause documents separately; literal credit_hours preserve fixed/fractional/range title evidence without choosing section credits or changing the Course integer field. description keyword evidence is not an interpreted enrollment rule. Read-time program_contexts include only same-edition source-checked plans explicitly naming the course, not personal applicability or merged grades. No edition/path is auto-selected and legacy edges remain unverified.
     */
    get: operations['get_course_course__course_id__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/course/{course_id}/requisites': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Read year-scoped prerequisite/corequisite clauses (not eligibility) */
    get: operations['get_course_requisites_course__course_id__requisites_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/feedback': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Submit Feedback */
    post: operations['submit_feedback_feedback_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/health': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Process liveness
     * @description Always 200 if the process responds — does **not** check whether the embedder/reranker have warmed. Use `/ready` for that. Suitable for Cloudflare Tunnel / docker / systemd healthcheck.
     */
    get: operations['health_health_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/privacy': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * The 数据与隐私 page, from the API's own settings (R2a)
     * @description The sections of the privacy page (heading and plain-text sentences, in page order), the note on what an account deletion removes, and the two notices next to the ask box. Built from this API's QUERY_LOG_RETENTION_DAYS, ANSWER_FEEDBACK_ENABLED and PRIVACY_CONTACT_EMAIL; `capture_notice` is null while answer feedback is off. The front end adds its own pointer to the page after `query_log_notice`.
     */
    get: operations['privacy_privacy_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/programs': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List seeded programs (with curriculum size)
     * @description Returns every seeded program with its required-course edge count. Public read, not gated content. Legacy seeds have unverified scope; plan_count counts usable version-scoped documents, not verified full degrees.
     *
     *     `course_count` counts curriculum EDGES (including edges whose course hasn't been scraped yet), so it can exceed the number of rows the curriculum view renders.
     */
    get: operations['list_programs_programs_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/programs/{program_id}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Program curriculum grouped by recommended semester
     * @description Returns one program's required courses grouped by `semester_recommended`, display names resolved from the catalog in a single batched SELECT.
     *
     *     Groups are ordered semester 1, 2, ... with the no-recommendation group (`semester: null` — no semester information, NOT anytime eligibility) last. Edges whose course_id is missing from the `courses` table (dangling seed edge, course not yet scraped) are silently dropped rather than failing the whole curriculum view.
     */
    get: operations['get_program_curriculum_programs__program_id__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/programs/{program_id}/plans': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Version-scoped requirement documents (not eligibility decisions) */
    get: operations['get_program_plans_programs__program_id__plans_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/programs/{program_id}/plans/{plan_id}/policies': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read-only evidence for one exact current plan, not eligibility
     * @description Missing, stale or unusable policy sources return explicit states with no usable fragments. No latest-edition fallback, auto-fetch, DB writes or merged policy decisions.
     */
    get: operations['get_selected_program_policies_programs__program_id__plans__plan_id__policies_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/ready': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lifespan readiness (models warmed, indexes loaded)
     * @description Returns `status='ready'` once the lifespan startup hook completed: FAISS index loaded, BM25 corpus built, bge-m3 embedder warmed, optional reranker warmed when enabled. Returns HTTP 503 with `status='warming'` while the retrieval stack is unavailable (~70-100 seconds of cold model load — see [PLAN_v2.0 §2.5](docs/PLAN_v2.0.md)).
     *
     *     HTTP 200 means ready. Orchestrators must not route user traffic on HTTP 503; `/health` remains the process-liveness endpoint.
     */
    get: operations['ready_ready_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/resolve/course': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Resolve a deep-link course reference to course_ids
     * @description Turns a shareable course reference into internal `course_id`s so the UI can open a `?course=` deep link.
     *
     *     Accepted forms: internal id (`neu-cs-5800`), canonical code with any URL separator (`CS-5800`, `CS_5800`, `CS+5800`, `CS 5800`), the space-free spelling (`cs5800`), and any **approved** alias (`Algo`) — the same `v_course_lookup` view `/search`'s alias stage uses, so `review_status='pending'` aliases are excluded.
     *
     *     Always 200. An unresolvable ref returns `matches: []` — a dead link is a normal outcome, not an error. `matches` may hold more than one course when the ref is ambiguous.
     *
     *     **Not** logged to `query_log`: deep-link resolution is machine traffic and must not contaminate organic-query telemetry.
     */
    get: operations['resolve_course_resolve_course_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/search': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Course search (alias → hybrid → rerank+blend+reject)
     * @description Production search path. Three-stage pipeline:
     *
     *     1. **Alias resolution** — `query_normalizer` strips/lowercases the query and looks it up in `v_course_lookup` (which excludes `review_status='pending'` aliases). On hit, returns immediately with `matched_via='alias'`, score=1.0. Covers `'CS 5800'` / `'cs5800'` / `'Algo'` / `'应用 AI'`.
     *     2. **Hybrid retrieval** — BM25 (110 stopwords filtered) + bge-m3 vector via Reciprocal Rank Fusion (RRF, k=60). Hard filters apply at SQLite layer; only `status='indexed'` rows surface (ADR-0013).
     *     3. **Rerank + Z-score blend + reject** (PLAN v2.2 §3.4 + §3.5) — single bge-reranker-v2-m3 pass over the candidate pool. If `max(raw_sigmoid) < 0.05` (ADR-0016): `matched_via='rejected'`, empty results, populated `rejection_reason`. Otherwise α=0.4 Z-score blend (ADR-0015) reorders the top-5 and returns `matched_via='hybrid'`.
     *
     *     **Latency budget**: alias path ~3ms, hybrid+rerank ~50ms p50 post-warmup.
     */
    post: operations['search_search_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /**
     * AIPolicy
     * @description Course's AI / generative-tool usage policy (v1.1).
     *
     *     Structured fields cover what students actually filter on:
     *     "is Copilot OK?", "is disclosure required?". Unstructured penalty/
     *     nuance text goes in `notes`.
     *
     *     中文:课程的 AI / 生成式工具使用政策(v1.1)。
     *
     *     结构化字段覆盖的是学生实际会用来筛选的问题:"能不能用 Copilot?"、
     *     "是否要求声明使用了 AI?"。非结构化的处罚细节 / 微妙之处放在 `notes` 里。
     */
    AIPolicy: {
      /** Banned Tools */
      banned_tools?: string[];
      /**
       * Disclosure Required
       * @default true
       */
      disclosure_required: boolean;
      /** Notes */
      notes?: string | null;
      /** Permitted Tools */
      permitted_tools?: string[];
    };
    /** AnswerFeedbackRequest */
    AnswerFeedbackRequest: {
      /** Answer Id */
      answer_id: string;
      /** Answer Sha256 */
      answer_sha256: string;
      /** Feedback Token */
      feedback_token: string;
      /**
       * Rating
       * @enum {string}
       */
      rating: 'up' | 'down';
    };
    /** AnswerFeedbackResponse */
    AnswerFeedbackResponse: {
      /** Answer Id */
      answer_id: string;
      /**
       * Rating
       * @enum {string}
       */
      rating: 'up' | 'down';
    };
    /**
     * AuthMeResponse
     * @description Identity behind a Bearer session token (GET /auth/me). Lets the UI
     *     restore login state from a persisted cookie without re-running OAuth —
     *     and re-reads contribution_count from the DB, so it's also the cheap
     *     "refresh my profile" call.
     *     Bearer 会话令牌背后的身份（GET /auth/me）。让 UI 能从持久化的 cookie
     *     恢复登录状态而无需重新走一遍 OAuth —— 同时会从数据库重读
     *     contribution_count，因此它也是一个低成本的"刷新我的资料"调用。
     */
    AuthMeResponse: {
      /**
       * Contribution Count
       * @default 0
       */
      contribution_count: number;
      /** Display Name */
      display_name?: string | null;
      /** Email */
      email: string;
      /** User Id */
      user_id: string;
    };
    /** CatalogCreditHours */
    CatalogCreditHours: {
      /**
       * Format Version
       * @default 1
       * @constant
       */
      format_version: '1';
      /**
       * Kind
       * @enum {string}
       */
      kind: 'fixed' | 'range';
      /** Maximum */
      maximum: string;
      /** Minimum */
      minimum: string;
      /** Raw Text */
      raw_text: string;
    };
    /** CatalogRequisites */
    CatalogRequisites: {
      corequisite: components['schemas']['RequisiteSection'];
      /**
       * Grammar Version
       * @default 1
       * @constant
       */
      grammar_version: '1';
      prerequisite: components['schemas']['RequisiteSection'];
    };
    /** CatalogSnapshot */
    CatalogSnapshot: {
      /** Catalog Url */
      catalog_url: string;
      /** Course Code */
      course_code: string;
      /** Course Name */
      course_name: string;
      /** Credits */
      credits?: number | null;
      /** Description */
      description?: string | null;
      /**
       * Imported At
       * Format: date-time
       */
      imported_at: string;
      /** Prereq Codes */
      prereq_codes?: string[];
      /** Retrieved At */
      retrieved_at?: string | null;
      /** Snapshot Id */
      snapshot_id: string;
    };
    /**
     * ChatRequest
     * @description Body for POST /chat. Filters mirror /search for re-use.
     *
     *     POST /chat 的请求体。过滤字段与 /search 保持一致，便于复用。
     *
     *     Conversation continuity (2026-06): `history` reaches the answer prompt
     *     (reference resolution + tone); `context_course_ids` are the previous
     *     turn's evidence — when the new query is a follow-up ("这门课作业量大吗"),
     *     retrieval short-circuits to those courses instead of searching a query
     *     that carries no course signal of its own.
     *
     *     对话连续性（2026-06）：`history` 会传到回答用的 prompt 里（用于指代
     *     消解 + 语气延续）；`context_course_ids` 是上一轮的证据 —— 当新查询是
     *     追问（如"这门课作业量大吗"）时，检索直接短路到这些课程，而不是去
     *     搜索一个本身不带任何课程信号的查询。
     */
    ChatRequest: {
      /**
       * Allow Feedback Capture
       * @default false
       */
      allow_feedback_capture: boolean;
      /** Context Course Ids */
      context_course_ids?: string[];
      /** Credits */
      credits?: number | null;
      /** Delivery Mode */
      delivery_mode?: string | null;
      /** History */
      history?: components['schemas']['ChatTurn'][];
      /**
       * K
       * @default 5
       */
      k: number;
      plan?: components['schemas']['PlanSelection'] | null;
      /** Professor */
      professor?: string | null;
      /** Program Id */
      program_id?: string | null;
      /** Query */
      query: string;
      /** Term */
      term?: string | null;
    };
    /**
     * ChatTurn
     * @description One prior conversation turn (client-supplied — /chat is stateless;
     *     the Streamlit session owns the transcript and sends a recent window).
     *     一轮此前的对话（由客户端提供 —— /chat 本身是无状态的；由 Streamlit
     *     会话保管完整记录，只发送最近的一段窗口）。
     */
    ChatTurn: {
      /** Content */
      content: string;
      /**
       * Role
       * @enum {string}
       */
      role: 'user' | 'assistant';
    };
    /**
     * CoopOut
     * @description Co-op view returned by GET /coop. Mirrors CoopExperience minus
     *     contributor_user_id / redaction_audit (internal audit fields, not for
     *     end users).
     *     GET /coop 返回的 Co-op 视图。与 CoopExperience 一致，但去掉了
     *     contributor_user_id / redaction_audit（内部审计字段，不面向终端
     *     用户）。
     */
    CoopOut: {
      /** Company */
      company: string;
      /** Coop Id */
      coop_id: string;
      /** Coop Term */
      coop_term: string | null;
      /** Duration Months */
      duration_months: number | null;
      /** Industry */
      industry: string | null;
      /** Interview Summary */
      interview_summary: string | null;
      /** Related Courses */
      related_courses: string[];
      /** Role */
      role: string;
      /** Salary Range Usd */
      salary_range_usd: string | null;
      /** Technical Questions */
      technical_questions: string | null;
      /** Visibility Level */
      visibility_level: number;
    };
    /**
     * CoopUploadRequest
     * @description Body for POST /coop. visibility_level is set server-side from content
     *     presence (interview / technical / salary), so clients don't pick their
     *     own tier.
     *     POST /coop 的请求体。visibility_level 由服务端根据内容是否存在
     *     （interview / technical / salary）来设定，客户端无法自选分层。
     */
    CoopUploadRequest: {
      /** Company */
      company: string;
      /** Coop Term */
      coop_term?: string | null;
      /** Duration Months */
      duration_months?: number | null;
      industry?: components['schemas']['Industry'] | null;
      /** Interview Summary */
      interview_summary?: string | null;
      /** Related Courses */
      related_courses?: string[];
      /** Role */
      role: string;
      /** Salary Range Usd */
      salary_range_usd?: string | null;
      /** Technical Questions */
      technical_questions?: string | null;
    };
    /** CoopUploadResponse */
    CoopUploadResponse: {
      /** Accepted */
      accepted: boolean;
      /** Contribution Count */
      contribution_count: number;
      /** Contribution Credited */
      contribution_credited: boolean;
      /** Coop Id */
      coop_id: string;
      /** Duplicate */
      duplicate: boolean;
      /**
       * Status
       * @enum {string}
       */
      status: 'pending' | 'approved' | 'rejected' | 'published';
      /** Visibility Level */
      visibility_level: number;
    };
    /** CourseAnswerEvidence */
    CourseAnswerEvidence: {
      catalog?: components['schemas']['CatalogSnapshot'] | null;
      /** Field Evidence */
      field_evidence?: components['schemas']['EvidenceSnippet'][];
      /** Missing Fields */
      missing_fields?: string[];
      requisites?: components['schemas']['RequisiteEvidence'] | null;
      /** Source Review Ids */
      source_review_ids?: string[];
      /** Warnings */
      warnings?: string[];
    };
    /** CourseDescriptionEvidence */
    CourseDescriptionEvidence: {
      /** Candidates */
      candidates?: components['schemas']['DescriptionCandidate'][];
      /**
       * Format Version
       * @default 1
       * @constant
       */
      format_version: '1';
      /** Paragraphs */
      paragraphs?: string[];
      /**
       * Status
       * @enum {string}
       */
      status: 'not_listed' | 'no_keyword_match' | 'review_needed';
    };
    /**
     * CourseDetailOut
     * @description Course (schema v1.1, unchanged fields) + program-ontology context.
     *
     *     Course（schema v1.1，字段未变）+ 培养方案本体上下文。
     *
     *     Subclass instead of wrapper so existing /course/{id} consumers keep
     *     their flat field access; the two new lists default to empty for
     *     courses outside any seeded program.
     *
     *     用子类而不是包装类，这样 /course/{id} 现有的消费方仍能保持扁平的
     *     字段访问方式；对不属于任何预置培养方案的课程，这两个新列表默认
     *     为空。
     */
    CourseDetailOut: {
      ai_policy?: components['schemas']['AIPolicy'] | null;
      answer_evidence?: components['schemas']['CourseAnswerEvidence'];
      /** Career Relevance */
      career_relevance?: string[];
      /** Controversial Signals */
      controversial_signals?: string[];
      /**
       * Course Id
       * @description Internal stable UUID
       */
      course_id: string;
      course_requisites?: components['schemas']['CourseRequisiteListing'];
      /**
       * Created At
       * Format: date-time
       */
      created_at?: string;
      /** Credits */
      credits?: number | null;
      delivery_mode?: components['schemas']['DeliveryMode'] | null;
      /** Difficulty Score */
      difficulty_score?: number | null;
      /** Evidence Snippets */
      evidence_snippets?: components['schemas']['EvidenceSnippet'][];
      /** Extraction Confidence */
      extraction_confidence?: number | null;
      /** Grading Components */
      grading_components?: components['schemas']['GradingComponent'][];
      instructor_contact?: components['schemas']['InstructorContact'] | null;
      meeting_schedule?: components['schemas']['MeetingSchedule'] | null;
      /** Prereqs */
      prereqs?: string[];
      /** Prerequisites */
      prerequisites?: components['schemas']['CoursePrereqOut'][];
      /**
       * Primary Code
       * @description Canonical code, e.g. 'CS 5800'
       */
      primary_code: string;
      /** Primary Name */
      primary_name: string;
      /** Professor */
      professor?: string[];
      /** Program Context */
      program_context?: components['schemas']['CourseProgramEdgeOut'][];
      /**
       * Schema Version
       * @default 1.1
       */
      schema_version: string;
      /** Skill Tags */
      skill_tags?: string[];
      /** Source Review Ids */
      source_review_ids?: string[];
      /** Term */
      term?: string | null;
      /** Textbooks */
      textbooks?: components['schemas']['Textbook'][];
      /** Topics Covered */
      topics_covered?: string[];
      /**
       * Updated At
       * Format: date-time
       */
      updated_at?: string;
      /** Workload Hours Per Week */
      workload_hours_per_week?: number | null;
    };
    /**
     * CoursePrereqOut
     * @description A prerequisite edge with the prereq's display fields resolved.
     *     code/name are None when the prereq course isn't in the catalog
     *     (dangling seed edge) — the UI then shows the raw course_id.
     *     一条先修边，先修课程的显示字段已解析。当先修课程不在目录中时
     *     （悬空的种子边），code/name 为 None —— 此时 UI 会直接显示原始
     *     course_id。
     */
    CoursePrereqOut: {
      /** Course Id */
      course_id: string;
      /** Primary Code */
      primary_code?: string | null;
      /** Primary Name */
      primary_name?: string | null;
      /** Requirement */
      requirement: string;
    };
    /** CourseProgramContext */
    CourseProgramContext: {
      /** Catalog Year */
      catalog_year: string;
      /** Course Code */
      course_code: string;
      /** Plans */
      plans?: components['schemas']['ProgramPlan'][];
      /**
       * Schema Available
       * @default false
       */
      schema_available: boolean;
      /**
       * Unreviewed Records
       * @default 0
       */
      unreviewed_records: number;
      /**
       * Unusable Records
       * @default 0
       */
      unusable_records: number;
      /** Warnings */
      warnings?: string[];
    };
    /**
     * CourseProgramEdgeOut
     * @description How a course fits into one seeded program (Layer 3 ontology).
     *     一门课程如何嵌入某个预置培养方案（Layer 3 本体）。
     */
    CourseProgramEdgeOut: {
      /** Program Id */
      program_id: string;
      /** Program Name */
      program_name: string;
      /** Requirement Type */
      requirement_type: string;
      /** Semester Recommended */
      semester_recommended?: number | null;
    };
    /**
     * CourseRange
     * @description A catalog code interval, not proof that every number is a real course.
     */
    CourseRange: {
      /** End */
      end: string;
      /** Start */
      start: string;
    };
    /** CourseRequisiteDocument */
    CourseRequisiteDocument: {
      /** Campus */
      campus?: null;
      /** Catalog Year */
      catalog_year: string;
      /** Course Code */
      course_code: string;
      /** Course Id */
      course_id: string;
      /** Course Name */
      course_name: string;
      /**
       * Coverage
       * @default courseblock_clauses_only
       * @constant
       */
      coverage: 'courseblock_clauses_only';
      credit_hours?: components['schemas']['CatalogCreditHours'] | null;
      description_evidence?:
        components['schemas']['CourseDescriptionEvidence'] | null;
      /**
       * Format Version
       * @default 1
       * @constant
       */
      format_version: '1';
      /**
       * Imported At
       * Format: date-time
       */
      imported_at?: string;
      requisites: components['schemas']['CatalogRequisites'];
      source: components['schemas']['CourseRequisiteSource'];
    };
    /** CourseRequisiteListing */
    CourseRequisiteListing: {
      /** Documents */
      documents?: components['schemas']['CourseRequisiteDocument'][];
      /**
       * Has Any Stored Records
       * @default false
       */
      has_any_stored_records: boolean;
      /** Program Contexts */
      program_contexts?: components['schemas']['CourseProgramContext'][];
      /**
       * Schema Available
       * @default false
       */
      schema_available: boolean;
      /**
       * Unusable Records
       * @default 0
       */
      unusable_records: number;
      /** Warnings */
      warnings?: string[];
    };
    /** CourseRequisiteSource */
    CourseRequisiteSource: {
      /** Byte Count */
      byte_count: number;
      /**
       * Captured At
       * Format: date-time
       */
      captured_at: string;
      /** Catalog Year */
      catalog_year: string;
      /**
       * Format Version
       * @default 1
       */
      format_version: number;
      /** Page Title */
      page_title: string;
      /** Sha256 */
      sha256: string;
      /** Url */
      url: string;
    };
    /**
     * CurriculumCourseOut
     * @description One course inside a semester group, display fields resolved from
     *     the catalog. Edges whose course_id is missing from `courses` (dangling
     *     seed edge) are dropped by the route, so code/name are always present.
     *     某个学期分组内的一门课程，显示字段已从目录解析。course_id 在 `courses`
     *     中缺失的边（悬空的种子边）会被路由丢弃，因此 code/name 必定存在。
     */
    CurriculumCourseOut: {
      /** Course Id */
      course_id: string;
      /** Notes */
      notes?: string | null;
      /** Primary Code */
      primary_code: string;
      /** Primary Name */
      primary_name: string;
      /** Requirement Type */
      requirement_type: string;
    };
    /**
     * CurriculumSemesterOut
     * @description Semester group. semester=None means 'no recorded recommendation', NOT
     *     permission to enroll in any term, and it always sorts last.
     *     学期分组。semester=None 表示"没有记录推荐学期"，不是任意学期可修，
     *     并且始终排在最后。
     */
    CurriculumSemesterOut: {
      /** Courses */
      courses: components['schemas']['CurriculumCourseOut'][];
      /** Semester */
      semester?: number | null;
    };
    /**
     * DayOfWeek
     * @enum {string}
     */
    DayOfWeek:
      | 'monday'
      | 'tuesday'
      | 'wednesday'
      | 'thursday'
      | 'friday'
      | 'saturday'
      | 'sunday';
    /**
     * DeleteAccountRequest
     * @description The word `delete`, so a stray POST never deletes an account (batch T, P4). 中文：要写明 `delete`。
     */
    DeleteAccountRequest: {
      /**
       * Confirm
       * @constant
       */
      confirm: 'delete';
    };
    /**
     * DeleteAccountResponse
     * @description Rows removed per kind; no identity. 中文：各类删了几行，不带身份。
     */
    DeleteAccountResponse: {
      /** Credits */
      credits: number;
      /**
       * Deleted
       * @default true
       * @constant
       */
      deleted: true;
      /** Own Unlocks */
      own_unlocks: number;
      /** Planned Courses */
      planned_courses: number;
      /** Published Experiences */
      published_experiences: number;
      /** Submissions */
      submissions: number;
      /** Unlocks Of Those */
      unlocks_of_those: number;
      /** Withdrawn From Groups */
      withdrawn_from_groups: number;
    };
    /**
     * DeliveryMode
     * @enum {string}
     */
    DeliveryMode: 'in_person' | 'online' | 'hybrid' | 'async';
    /** DescriptionCandidate */
    DescriptionCandidate: {
      /** Markers */
      markers: (
        | 'permission'
        | 'approval'
        | 'admission'
        | 'eligibility'
        | 'restriction'
        | 'registration'
        | 'qualification'
      )[];
      /** Paragraph Index */
      paragraph_index: number;
    };
    /**
     * EvidenceSnippet
     * @description One quote backing a soft field value (PLAN §2.3).
     *
     *     中文:支撑某个软字段(soft field)取值的一条引用证据(PLAN §2.3)。
     */
    EvidenceSnippet: {
      /** Confidence */
      confidence: number;
      /**
       * Field
       * @description Soft field this evidence supports, e.g. 'difficulty_score'
       */
      field: string;
      /** Quote */
      quote: string;
      /**
       * Source Id
       * @description e.g. 'rmp_review_98765', 'reddit_t1_abc'
       */
      source_id: string;
      /**
       * Value
       * @description The supported value (matches the soft field's type)
       */
      value: unknown;
    };
    /**
     * GradingComponent
     * @description One row of the grading rubric, e.g. {'name': 'midterm', 'weight': 0.3}.
     *
     *     weight is Optional in v1.1 — most CPS syllabi don't publish exact weights.
     *     Recording {name: "discussion board", weight: None} is preferred to dropping
     *     the entry entirely (which loses the fact that this component exists).
     *
     *     中文:评分细则(grading rubric)中的一行,例如
     *     {'name': 'midterm', 'weight': 0.3}。
     *
     *     weight 在 v1.1 中是 Optional 的 —— 大多数 CPS 课程大纲并不公布具体的
     *     权重数字。记录 {name: "discussion board", weight: None} 比整条丢弃更
     *     可取(整条丢弃会连"这个评分项存在"这个事实一起丢掉)。
     */
    GradingComponent: {
      /** Name */
      name: string;
      /** Weight */
      weight?: number | null;
    };
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components['schemas']['ValidationError'][];
    };
    /** HealthResponse */
    HealthResponse: {
      /**
       * Status
       * @default ok
       * @constant
       */
      status: 'ok';
    };
    /**
     * Industry
     * @description Industry buckets used for analytics + k-anonymity filtering.
     *
     *     PLAN §6.5 Seed Data distribution targets:
     *       QUANT_FINTECH: 12  (State Street, Fidelity, Wellington, MFS, Putnam)
     *       BIG_TECH:      8   (Amazon, Google, Microsoft Boston offices)
     *       BIOTECH_HEALTH: 5  (Moderna, Vertex, IQVIA)
     *       STARTUP:       5   (Boston AI startup ecosystem)
     *
     *     中文:用于数据分析 + k-匿名(k-anonymity)过滤的行业分桶。
     *
     *     PLAN §6.5 种子数据(Seed Data)分布目标:
     *       QUANT_FINTECH:  12(State Street、Fidelity、Wellington、MFS、Putnam)
     *       BIG_TECH:        8(Amazon、Google、Microsoft 波士顿办公室)
     *       BIOTECH_HEALTH:  5(Moderna、Vertex、IQVIA)
     *       STARTUP:         5(波士顿 AI 创业生态圈)
     * @enum {string}
     */
    Industry:
      | 'quant_fintech'
      | 'big_tech'
      | 'biotech_health'
      | 'startup'
      | 'consulting'
      | 'other';
    /**
     * InstructorContact
     * @description Instructor contact info (v1.1).
     *
     *     name typically duplicates Course.professor[0] but stays here for
     *     standalone use. Email is OK to store: NEU faculty emails are publicly
     *     listed on the directory; this is not protected PII like student emails.
     *
     *     中文:授课教师的联系方式(v1.1)。
     *
     *     name 通常与 Course.professor[0] 重复,但仍单独保留在这里以便独立使用。
     *     Email 可以放心存储:NEU 教职工邮箱在教职工目录中是公开信息,不像学生
     *     邮箱那样属于需要保护的 PII。
     */
    InstructorContact: {
      /** Email */
      email?: string | null;
      /** Name */
      name: string;
      /**
       * Office Hours
       * @description Free-form: 'Tue 3-5 PM @ Snell 410' or 'by appointment via email'
       */
      office_hours?: string | null;
      /**
       * Secondary Contact
       * @description e.g. academic lead's name + email
       */
      secondary_contact?: string | null;
    };
    /**
     * LoginUrlResponse
     * @description GET /auth/login-url: where to send the browser to log in with Google (R2a). 中文：去 Google 登录的地址。
     */
    LoginUrlResponse: {
      /** Url */
      url: string;
    };
    /**
     * MeetingSchedule
     * @description Full meeting schedule for a course (v1.1).
     *
     *     中文:某门课程完整的上课时间表(v1.1)。
     */
    MeetingSchedule: {
      /** End Date */
      end_date?: string | null;
      /** Slots */
      slots?: components['schemas']['MeetingSlot'][];
      /** Start Date */
      start_date?: string | null;
      /**
       * Timezone
       * @default America/New_York
       */
      timezone: string;
    };
    /**
     * MeetingSlot
     * @description One day-of-week meeting (v1.1).
     *
     *     A course can have multiple slots (e.g. M+W+F). times use
     *     Pydantic's `time` type — accepts '17:50' string and serializes
     *     to ISO 'HH:MM:SS'.
     *
     *     中文:每周固定某一天的一次上课时段(v1.1)。
     *
     *     一门课可以有多个时段(例如周一+周三+周五)。时间字段使用 Pydantic 的
     *     `time` 类型 —— 接受 '17:50' 这样的字符串输入,序列化为 ISO
     *     'HH:MM:SS' 格式输出。
     */
    MeetingSlot: {
      day_of_week: components['schemas']['DayOfWeek'];
      /**
       * End Time
       * Format: time
       */
      end_time: string;
      /**
       * Location
       * @description e.g. 'Snell Library 119' or 'Online'
       */
      location?: string | null;
      /**
       * Start Time
       * Format: time
       */
      start_time: string;
    };
    /**
     * OAuthCallbackRequest
     * @description Body for POST /auth/callback. The Streamlit page sends the `code`
     *     query param Google redirected back with.
     *     POST /auth/callback 的请求体。Streamlit 页面发送 Google 重定向带回的
     *     `code` 查询参数。
     */
    OAuthCallbackRequest: {
      /** Code */
      code: string;
      /** Redirect Uri */
      redirect_uri?: string | null;
      /**
       * Session
       * @default token
       * @enum {string}
       */
      session: 'token' | 'cookie';
    };
    /**
     * OAuthCallbackResponse
     * @description Sanitized identity persisted server-side. Streamlit calls
     *     state_manager.login with these fields.
     *
     *     经清洗、已持久化到服务端的身份信息。Streamlit 会用这些字段调用
     *     state_manager.login。
     *
     *     session_token (ADR-0021): signed bearer credential for subsequent API
     *     calls (`Authorization: Bearer <token>`). None when the server runs
     *     without SESSION_SECRET (dev degraded mode), and None in the cookie mode
     *     (R2a), where the token is in the HttpOnly cookie instead.
     *
     *     session_token（ADR-0021）：供后续 API 调用使用的签名 bearer 凭证
     *     （`Authorization: Bearer <token>`）。服务端未配置 SESSION_SECRET 时
     *     （开发降级模式）为 None；cookie 模式（R2a）下也是 None，令牌在 HttpOnly
     *     cookie 里。
     */
    OAuthCallbackResponse: {
      /**
       * Contribution Count
       * @default 0
       */
      contribution_count: number;
      /** Display Name */
      display_name?: string | null;
      /** Email */
      email: string;
      /** Session Token */
      session_token?: string | null;
      /** User Id */
      user_id: string;
    };
    /** PlanPolicyLink */
    PlanPolicyLink: {
      /** Campus */
      campus: string;
      /** Catalog Year */
      catalog_year: string;
      /** Concentration */
      concentration?: string | null;
      /**
       * Home College
       * @enum {string}
       */
      home_college: 'khoury' | 'camd' | 'engineering';
      /**
       * Pathway
       * @enum {string}
       */
      pathway: 'standard' | 'align' | 'bridge';
      /** Plan Content Sha256 */
      plan_content_sha256: string;
      /** Plan Id */
      plan_id: string;
      /** Policy Ids */
      policy_ids: string[];
      /** Program Id */
      program_id: string;
    };
    /** PlanSelection */
    PlanSelection: {
      /** Campus */
      campus: string;
      /** Catalog Year */
      catalog_year: string;
      /** Concentration */
      concentration?: string | null;
      /**
       * Pathway
       * @enum {string}
       */
      pathway: 'standard' | 'align' | 'bridge';
      /** Plan Content Sha256 */
      plan_content_sha256: string;
      /** Plan Id */
      plan_id: string;
      /** Program Id */
      program_id: string;
    };
    /** PolicyEvidenceOut */
    PolicyEvidenceOut: {
      /**
       * Authority
       * @enum {string}
       */
      authority: 'university' | 'khoury' | 'camd' | 'engineering';
      /**
       * Coverage
       * @default selected_fragments_only
       * @constant
       */
      coverage: 'selected_fragments_only';
      /** Fragments */
      fragments: components['schemas']['PolicyFragmentOut'][];
      /** Policy Id */
      policy_id: string;
      source: components['schemas']['SourceCapture'];
    };
    /** PolicyFragmentOut */
    PolicyFragmentOut: {
      /** Fragment Id */
      fragment_id: string;
      /** Heading */
      heading?: string | null;
      /** Limitation */
      limitation: string;
      /** Paragraph Index */
      paragraph_index: number;
      /** Paragraph Sha256 */
      paragraph_sha256: string;
      /**
       * Source Kind
       * @default paragraph
       * @enum {string}
       */
      source_kind: 'paragraph' | 'list';
      /** Source Paragraph */
      source_paragraph: string;
      /** Summary */
      summary: string;
    };
    /** PolicyScope */
    PolicyScope: {
      /** Campus */
      campus: string;
      /** Catalog Year */
      catalog_year: string;
      /** Concentration */
      concentration?: string | null;
      /**
       * Pathway
       * @enum {string}
       */
      pathway: 'standard' | 'align' | 'bridge';
      /** Program Id */
      program_id: string;
    };
    /**
     * PrivacyResponse
     * @description GET /privacy (R2a): the 数据与隐私 page, built from the API's own settings, plus the two notices shown next to
     *     the ask box. 中文：「数据与隐私」页，按 API 自己的设置生成，外加提问框旁边的两段说明。
     */
    PrivacyResponse: {
      /** Capture Notice */
      capture_notice: string | null;
      /** Delete What */
      delete_what: string;
      /** Intro */
      intro: string;
      /** Query Log Notice */
      query_log_notice: string;
      /** Sections */
      sections: components['schemas']['PrivacySectionOut'][];
    };
    /** PrivacySectionOut */
    PrivacySectionOut: {
      /** Heading */
      heading: string;
      /** Sentences */
      sentences: string[];
    };
    /** ProgramCurriculumOut */
    ProgramCurriculumOut: {
      /** Full Name */
      full_name: string;
      /** Notes */
      notes?: string | null;
      /**
       * Plan Schema Available
       * @default false
       */
      plan_schema_available: boolean;
      /** Plans */
      plans?: components['schemas']['ProgramPlan'][];
      /** Prefix */
      prefix: string;
      /** Program Id */
      program_id: string;
      /** Semesters */
      semesters: components['schemas']['CurriculumSemesterOut'][];
      /** Warnings */
      warnings?: string[];
    };
    /** ProgramPlan */
    ProgramPlan: {
      /** Campus */
      campus: string;
      /**
       * Captured On
       * Format: date
       */
      captured_on: string;
      /** Catalog Year */
      catalog_year: string;
      /** Checked By */
      checked_by?: string | null;
      /** Checked On */
      checked_on?: string | null;
      /** Concentration */
      concentration?: string | null;
      /**
       * Coverage
       * @default partial
       * @enum {string}
       */
      coverage: 'partial' | 'complete';
      /** Notes */
      notes: string;
      /**
       * Pathway
       * @enum {string}
       */
      pathway: 'standard' | 'align' | 'bridge';
      /** Plan Id */
      plan_id: string;
      /** Program Id */
      program_id: string;
      requirements: components['schemas']['RequirementNode'];
      /**
       * Review Status
       * @default draft
       * @enum {string}
       */
      review_status: 'draft' | 'source_checked';
      /** Source Catalog Year */
      source_catalog_year: string;
      /** Source Excerpt */
      source_excerpt: string;
      /** Source Html Sha256 */
      source_html_sha256?: string | null;
      /** Source Title */
      source_title: string;
      /** Source Url */
      source_url: string;
    };
    /** ProgramPlansOut */
    ProgramPlansOut: {
      /** Plans */
      plans: components['schemas']['ProgramPlan'][];
      /** Program Id */
      program_id: string;
      /** Schema Available */
      schema_available: boolean;
      /** Warnings */
      warnings?: string[];
    };
    /** ProgramPolicyView */
    ProgramPolicyView: {
      /** Checked By */
      checked_by?: string | null;
      /** Checked On */
      checked_on?: string | null;
      /**
       * Coverage
       * @default selected_fragments_only
       * @constant
       */
      coverage: 'selected_fragments_only';
      link?: components['schemas']['PlanPolicyLink'] | null;
      /** Plan Content Sha256 */
      plan_content_sha256: string;
      /** Plan Id */
      plan_id: string;
      /** Policies */
      policies?: components['schemas']['PolicyEvidenceOut'][];
      scope: components['schemas']['PolicyScope'];
      /**
       * Status
       * @enum {string}
       */
      status:
        'ready' | 'not_linked' | 'draft' | 'stale' | 'unavailable' | 'unusable';
      /** Warnings */
      warnings?: string[];
    };
    /**
     * ProgramSummaryOut
     * @description One row of the /programs listing: Program + its curriculum size.
     *     /programs 列表里的一行：一个 Program 及其课程表规模。
     */
    ProgramSummaryOut: {
      /** College */
      college?: string | null;
      /** Course Count */
      course_count: number;
      /** Department */
      department?: string | null;
      /** Full Name */
      full_name: string;
      /**
       * Plan Count
       * @default 0
       */
      plan_count: number;
      /** Prefix */
      prefix: string;
      /** Program Id */
      program_id: string;
      /** Warnings */
      warnings?: string[];
    };
    /**
     * PublicConfigResponse
     * @description GET /config (R2a): what the web front end needs to know about this API. 中文：新前端要知道的公开设置。
     */
    PublicConfigResponse: {
      /** Answer Feedback Enabled */
      answer_feedback_enabled: boolean;
      /** Login Available */
      login_available: boolean;
    };
    /** ReadyResponse */
    ReadyResponse: {
      /** Bm25 Corpus */
      bm25_corpus: number;
      /** Courses Indexed */
      courses_indexed: number;
      /**
       * Status
       * @enum {string}
       */
      status: 'ready' | 'warming';
    };
    /** RequirementNode */
    RequirementNode: {
      /** Activate When */
      activate_when?: string | null;
      /** Areas */
      areas?: {
        [key: string]: string[];
      };
      /** Children */
      children?: components['schemas']['RequirementNode'][];
      /** Course Code */
      course_code?: string | null;
      /** Course Codes */
      course_codes?: string[];
      /** Course Ranges */
      course_ranges?: components['schemas']['CourseRange'][];
      /** Excluded Course Codes */
      excluded_course_codes?: string[];
      /**
       * Kind
       * @enum {string}
       */
      kind:
        | 'course'
        | 'all_of'
        | 'any_of'
        | 'select'
        | 'optional'
        | 'condition'
        | 'unmodeled';
      /** Label */
      label: string;
      /** Min Areas */
      min_areas?: number | null;
      /** Min Courses */
      min_courses?: number | null;
      /** Min Credits */
      min_credits?: number | null;
      /** Subject Codes */
      subject_codes?: string[];
    };
    /**
     * RequisiteEdition
     * @description One catalog year's course-block rules for a course, with where and when they were captured.
     */
    RequisiteEdition: {
      /**
       * Captured At
       * Format: date-time
       */
      captured_at: string;
      /** Catalog Url */
      catalog_url: string;
      /** Catalog Year */
      catalog_year: string;
      corequisite: components['schemas']['RequisiteSectionEvidence'];
      prerequisite: components['schemas']['RequisiteSectionEvidence'];
    };
    /**
     * RequisiteEvidence
     * @description The year-scoped prerequisite documents an answer may use for one course.
     *
     *     storage: available, schema_missing (no table) or schema_unusable (the table cannot be read).
     *     editions: usable documents, newest catalog year first, at most MAX_REQUISITE_EDITIONS;
     *     editions_omitted counts the other usable ones. unusable_records: stored documents that failed
     *     the identity, hash or tree checks, or belong to a year with two passing documents (possible
     *     only in a copy without keys; neither is used). A year's one passing row is kept if its twins fail.
     *     中文：一门课的回答可用的年度先修文档。storage：可用、没有表、表读不了。editions：可用文档，按
     *     Catalog 年度从新到旧，最多 MAX_REQUISITE_EDITIONS 份，editions_omitted 是其余可用的份数。
     *     unusable_records：身份、hash 或规则树核对不过的已存文档，以及同年度有两份都通过核对的文档（只有
     *     缺键的副本里才会有，两份都不用）；同年度只有一份通过核对则保留它，其余计入不可用。
     */
    RequisiteEvidence: {
      /** Editions */
      editions?: components['schemas']['RequisiteEdition'][];
      /**
       * Editions Omitted
       * @default 0
       */
      editions_omitted: number;
      /**
       * Other Years Recorded
       * @default 0
       */
      other_years_recorded: number;
      /** Selected Year */
      selected_year?: string | null;
      /**
       * Storage
       * @enum {string}
       */
      storage: 'available' | 'schema_missing' | 'schema_unusable';
      /**
       * Unusable Records
       * @default 0
       */
      unusable_records: number;
    };
    /** RequisiteNode */
    RequisiteNode: {
      /** Academic Level */
      academic_level?: ('Graduate' | 'Undergraduate') | null;
      /** Children */
      children?: components['schemas']['RequisiteNode'][];
      /**
       * Concurrent Allowed
       * @default false
       */
      concurrent_allowed: boolean;
      /** Course Code */
      course_code?: string | null;
      /**
       * Kind
       * @enum {string}
       */
      kind: 'course' | 'all_of' | 'any_of';
      /** Minimum Grade */
      minimum_grade?:
        | (
            | 'A+'
            | 'A'
            | 'A-'
            | 'B+'
            | 'B'
            | 'B-'
            | 'C+'
            | 'C'
            | 'C-'
            | 'D+'
            | 'D'
            | 'D-'
            | 'F'
            | 'P'
            | 'S'
          )
        | null;
    };
    /** RequisiteSection */
    RequisiteSection: {
      /** Raw Text */
      raw_text?: string | null;
      /** Reason */
      reason?: string | null;
      rule?: components['schemas']['RequisiteNode'] | null;
      /**
       * Status
       * @enum {string}
       */
      status: 'not_listed' | 'parsed' | 'unparsed';
    };
    /**
     * RequisiteSectionEvidence
     * @description One prerequisite or corequisite section of a stored year document, as an answer sees it:
     *     the same status and rule tree, the recorded clause text cut to CLAUSE_LIMIT characters. An
     *     unparsed section also carries the SHA-256 of its whole recorded text, which years are compared
     *     by (so texts that differ only after the cut still differ); it never reaches the prompt.
     *     中文：已存年度文档里的一段先修或共修，回答看到的样子：状态和规则树不变，条款原文截到
     *     CLAUSE_LIMIT 个字符。未解析的一段另带整段原文的 SHA-256，各年度按它比较（所以截断处以后才
     *     不同也算不同）；它不进提示词。
     */
    RequisiteSectionEvidence: {
      /** Clause Sha256 */
      clause_sha256?: string | null;
      /** Clause Text */
      clause_text?: string | null;
      /**
       * Clause Truncated
       * @default false
       */
      clause_truncated: boolean;
      rule?: components['schemas']['RequisiteNode'] | null;
      /**
       * Status
       * @enum {string}
       */
      status: 'not_listed' | 'parsed' | 'unparsed';
      /** Unparsed Reason */
      unparsed_reason?: string | null;
    };
    /**
     * ResolveCourseResponse
     * @description `matches` is empty when nothing resolved — a dead deep link is a
     *     normal outcome, not a 404. Clients treat ApiError as "API is down",
     *     so surfacing "no such course" as an exception would misreport it.
     *     没解析出任何结果时 `matches` 为空 —— 失效的深链是正常结果，不是 404。
     *     客户端把 ApiError 一律理解为「API 挂了」，若把「查无此课」抛成异常
     *     就会误报。
     */
    ResolveCourseResponse: {
      /** Matches */
      matches: components['schemas']['ResolvedCourseOut'][];
      /** Ref */
      ref: string;
    };
    /**
     * ResolvedCourseOut
     * @description One course a deep-link ref resolved to. Code + name ride along with
     *     the id so an ambiguous ref can be disambiguated in the UI without N
     *     follow-up /course calls.
     *     深链 ref 解析出的一门课程。code + name 与 id 一起返回，这样 UI 在遇到
     *     有歧义的 ref 时无需再发 N 次 /course 请求就能做消歧。
     */
    ResolvedCourseOut: {
      /** Course Id */
      course_id: string;
      /** Primary Code */
      primary_code: string;
      /** Primary Name */
      primary_name: string;
    };
    /** SearchHitOut */
    SearchHitOut: {
      /** Course Id */
      course_id: string;
      /**
       * Matched Via
       * @enum {string}
       */
      matched_via: 'alias' | 'hybrid';
      /** Primary Code */
      primary_code: string;
      /** Primary Name */
      primary_name: string;
      /** Score */
      score: number;
    };
    /**
     * SearchRequest
     * @description Search query body. Filters are optional; all combine with AND.
     *     搜索请求体。过滤条件均为可选，多个条件之间以 AND 组合。
     */
    SearchRequest: {
      /** Credits */
      credits?: number | null;
      /** Delivery Mode */
      delivery_mode?: string | null;
      /**
       * K
       * @default 10
       */
      k: number;
      /** Professor */
      professor?: string | null;
      /** Query */
      query: string;
      /** Term */
      term?: string | null;
    };
    /** SearchResponse */
    SearchResponse: {
      /** K */
      k: number;
      /** Latency Ms */
      latency_ms: number;
      /**
       * Matched Via
       * @enum {string}
       */
      matched_via: 'alias' | 'hybrid' | 'empty' | 'rejected';
      /** Query */
      query: string;
      /** Rejection Reason */
      rejection_reason?: string | null;
      /** Results */
      results: components['schemas']['SearchHitOut'][];
    };
    /** SourceCapture */
    SourceCapture: {
      /** Byte Count */
      byte_count: number;
      /**
       * Captured At
       * Format: date-time
       */
      captured_at: string;
      /** Catalog Year */
      catalog_year: string;
      /**
       * Format Version
       * @default 1
       */
      format_version: number;
      /** Page Title */
      page_title: string;
      /** Sha256 */
      sha256: string;
      /** Url */
      url: string;
    };
    /**
     * Textbook
     * @description Required or optional textbook (v1.1).
     *
     *     中文:必读或选读教材(v1.1)。
     */
    Textbook: {
      /** Authors */
      authors?: string[];
      /**
       * Is Required
       * @default true
       */
      is_required: boolean;
      /** Isbn */
      isbn?: string | null;
      /** Title */
      title: string;
      /** Url */
      url?: string | null;
    };
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>;
      /** Input */
      input?: unknown;
      /** Location */
      loc: (string | number)[];
      /** Message */
      msg: string;
      /** Error Type */
      type: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  oauth_callback_auth_callback_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['OAuthCallbackRequest'];
      };
    };
    responses: {
      /** @description OAuth round-trip succeeded; user persisted. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['OAuthCallbackResponse'];
        };
      };
      /** @description Code exchange failed, JWT invalid, or email domain not in whitelist (`husky.neu.edu` / `northeastern.edu`). Besides the fixed `detail`, the body has `reason` (R2b): `token_exchange_rejected`, `token_endpoint_unreachable`, `missing_id_token`, `id_token_invalid`, `claims_invalid`, `email_unverified` or `domain_not_allowed`. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The cookie mode, not from an allowed web origin with `X-NEU-Compass: 1`. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The body is malformed, or the cookie mode's `redirect_uri` is not the request's own `Origin` followed by `/`. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  delete_account_auth_delete_account_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['DeleteAccountRequest'];
      };
    };
    responses: {
      /** @description Deleted; counts of the rows removed. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['DeleteAccountResponse'];
        };
      };
      /** @description Missing, invalid or expired token, or the account no longer exists. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description The body is not exactly `{"confirm": "delete"}`. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  login_url_auth_login_url_get: {
    parameters: {
      query: {
        state: string;
        redirect_uri?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description The address to send the browser to. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['LoginUrlResponse'];
        };
      };
      /** @description `state` is not 16–128 characters of A–Z, a–z, 0–9, `_` or `-`, or `redirect_uri` is not a web front end's own address. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Login is not configured here (no Google client ID or secret, or no SESSION_SECRET). */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  logout_auth_logout_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description The session cookie, if any, is expired. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Not from an allowed web origin with `X-NEU-Compass: 1`. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  auth_me_auth_me_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Token valid; identity returned. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['AuthMeResponse'];
        };
      };
      /** @description Missing, invalid, or expired token — or the token's user row no longer exists. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  chat_chat_post: {
    parameters: {
      query?: never;
      header?: {
        'x-eval-run'?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['ChatRequest'];
      };
    };
    responses: {
      /** @description NDJSON event stream. See description for shape. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
          'application/x-ndjson': unknown;
        };
      };
      /** @description Program selection is ambiguous or conflicts with the query's program prefix. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Invalid query / k / delivery_mode. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  public_config_config_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PublicConfigResponse'];
        };
      };
    };
  };
  list_coop_coop_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Eligible public Co-op records (redacted per tier). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CoopOut'][];
        };
      };
    };
  };
  upload_coop_coop_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['CoopUploadRequest'];
      };
    };
    responses: {
      /** @description Private submission stored, or existing submission returned. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CoopUploadResponse'];
        };
      };
      /** @description Missing, invalid, expired token, or unknown user. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Invalid payload. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Moderation schema has not been migrated. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  get_course_course__course_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        course_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Course found and returned. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CourseDetailOut'];
        };
      };
      /** @description course_id not in `courses` table. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  get_course_requisites_course__course_id__requisites_get: {
    parameters: {
      query?: {
        catalog_year?: string | null;
      };
      header?: never;
      path: {
        course_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CourseRequisiteListing'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  submit_feedback_feedback_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['AnswerFeedbackRequest'];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['AnswerFeedbackResponse'];
        };
      };
      /** @description Receipt invalid, expired or unavailable */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
      /** @description Feedback schema/storage unavailable */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  health_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HealthResponse'];
        };
      };
    };
  };
  privacy_privacy_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PrivacyResponse'];
        };
      };
    };
  };
  list_programs_programs_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Program list (possibly empty before seeding). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProgramSummaryOut'][];
        };
      };
    };
  };
  get_program_curriculum_programs__program_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        program_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Curriculum found and returned. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProgramCurriculumOut'];
        };
      };
      /** @description program_id not in `programs` table. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  get_program_plans_programs__program_id__plans_get: {
    parameters: {
      query?: {
        campus?: string | null;
        catalog_year?: string | null;
        pathway?: string | null;
      };
      header?: never;
      path: {
        program_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProgramPlansOut'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  get_selected_program_policies_programs__program_id__plans__plan_id__policies_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        program_id: string;
        plan_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProgramPolicyView'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  ready_ready_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReadyResponse'];
        };
      };
      /** @description Retrieval stack not ready. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReadyResponse'];
        };
      };
    };
  };
  resolve_course_resolve_course_get: {
    parameters: {
      query: {
        /** @description The raw `?course=` value, e.g. `CS-5800`. */
        ref: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Resolution ran. `matches` is ordered most-specific first and is `[]` when nothing matched. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ResolveCourseResponse'];
        };
      };
      /** @description `ref` missing, empty, or absurdly long. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  search_search_post: {
    parameters: {
      query?: never;
      header?: {
        'x-eval-run'?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        'application/json': components['schemas']['SearchRequest'];
      };
    };
    responses: {
      /** @description Search resolved. `matched_via` ∈ {alias, hybrid, empty, rejected}. `results=[]` when matched_via is empty or rejected; `rejection_reason` is non-null only when rejected. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SearchResponse'];
        };
      };
      /** @description Invalid request (empty query, k out of range, unknown delivery_mode, extra unknown fields). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
}
