# Week 7 Postmortem — 公网软启动 8 类踩坑

> **范围**: 2026-04-30 至 2026-05-04, Week 7 Cloudflare Tunnel 部署 + 全 OAuth round-trip + 3-course Gemini smoke。
> **背景**: PLAN v2.2 §3.1-§3.7 全 P0/P1/P2 交付,过程中暴露 8 类问题,全部已修 + 文档化。
> **目的**: 工程经验沉淀;portfolio packaging 的"踩坑可信度"原料 (PLAN v2.3 §3.7)。

每条按 **症状 / 根因 / 修复 / 启示** 四段。

---

## 1. Google Cloud Console OAuth client 创建流程跌出旧文档

**症状**: 按旧 Stack Overflow / 旧 PLAN 步骤建 OAuth client,OAuth consent screen 找不到了,test users 配置完一登就 400。

**根因**: Google 2026Q1 改版 Auth Platform UI:
- "OAuth consent screen" 改名 "OAuth 同意屏幕" / "受众群体"
- branding / scopes / test users **拆三个独立页**(原本一页),漏配任何一页都 400
- Test users 必须**包含开发者邮箱**(production 模式之外的强制)

**修复**: 走完三页,test users 加自己的 husky.neu.edu + northeastern.edu 各一份。

**启示**: 第三方 console UI 改版无 changelog,部署文档每 6 个月须重测一遍 — 写进 `docs/cloudflare_tunnel.md` §11.4。

---

## 2. `hd=husky.neu.edu` 锁死单域,northeastern.edu 用户无法登录

**症状**: husky.neu.edu 邮箱登录通,northeastern.edu 邮箱在 Google 登录页被拒,显示 "This domain is not allowed for this app"。

**根因**: `app/auth.py` 早期版本在 OAuth authorize URL 里写死 `hd=husky.neu.edu` 作为 hint。Google 的 `hd` 参数**只接受单值**,但 `settings.allowed_email_domains` 是 `{husky.neu.edu, northeastern.edu}` 双域白名单 — 二者不兼容。

**修复**: 移除 `hd` 参数。域名白名单**只在 server-side `is_email_allowed`** 强制(已有,split-on-`@` 精确匹配)。客户端 hint 牺牲,server 防御足够。

**启示**: client-side hint 跟 server-side enforcement 不要同时收紧 — 容易出现 hint 比 enforcement 更严的情况,反而误拒合法用户。

---

## 3. cloudflared 不支持 strip path-prefix → 单域 + path 路由失败

**症状**: 设计 `compass.<zone>.com/api/*` → uvicorn,边缘看 200 但 uvicorn 报 404 — 因为 uvicorn 收到的路径是 `/api/health` 而它的路由是 `/health`。

**根因**: cloudflared 的 ingress `path` 规则**只匹配不重写**。Nginx / Traefik / Envoy 都支持的 strip-prefix 在 cloudflared 没有。

**修复**: 切换到**双子域**架构:
- `api.neu-compass.me` → `localhost:8000` (FastAPI)
- `compass.neu-compass.me` → `localhost:8501` (Streamlit + OAuth callback)

FastAPI 路径不需任何改动;Streamlit OAuth callback 也回到根路径。

**启示**: 同一域名下后端 path 路由是 nginx 时代的反射习惯 — Cloudflare Tunnel 时代 DNS 子域更便宜更直观。新部署直接走子域,不走 path-prefix。

---

## 4. Streamlit 在 OAuth subpath 下相对路径加载 JS 失败 → 白屏

**症状**: `redirect_uri=https://compass.../oauth/callback` 触发 Streamlit 渲染 callback HTML,但页面白屏。F12 Console: `static/main.js 404`。

**根因**: Streamlit HTML 引用 JS 是 `./static/...` 相对路径。浏览器在 `/oauth/callback` 上下文里把它解析成 `/oauth/static/main.js` → Streamlit server 在 `/oauth/static/` 路径不存在 → 404 → 白屏。

**修复**: 改 OAuth redirect URI 到根路径 `/`,`handle_oauth_callback` 仍读 `?code=` 查询参数(与路径无关)。Google OAuth Console 同步改 Authorized redirect URI。

**启示**: 单页应用 + 任何 base path 都要测 JS asset 加载。Streamlit 没有 `--server.baseUrlPath` 之外的 path-aware 配置,默认行为就是相对路径 — 任何子路径部署都会触发这个。

---

## 5. uvicorn 进程持有 settings 缓存 → 改 .env 后只重启 streamlit 也不够

**症状**: 改 .env 把 `GOOGLE_OAUTH_REDIRECT_URI` 从 localhost 切到公网,只重启 streamlit。OAuth round-trip 报 `invalid_grant`。

**根因**: `config.settings` 是 pydantic-settings 单例,uvicorn 进程启动时一次性读 .env。Streamlit 边重启读了新值发 authorize_url 走公网,但 uvicorn 边换 token 仍用旧 redirect_uri(localhost)。Google 校验"authorize 时的 redirect_uri" vs "token 换时的 redirect_uri" 不一致 → 拒绝。

**修复**: 改 .env 后**两个进程都得重启**(uvicorn + streamlit)。runbook 加了显式步骤。

**启示**: 任何用 `lru_cache` / 单例 settings 的进程都要把 ".env 改了 → 重启" 写进 runbook。考虑做一个 `make restart` 一键命令。

---

## 6. Runtime DB schema drift → migrate_db_to_v1_1.py ALTER TABLE 补齐

**症状**: 公网起来后 `POST /coop` 报 `no such column: coop_experiences.industry`。

**根因**: 运行时 DB 是 2026-04-30 旧 init.sql 建的,schema 1.0 版本。中间 schema 升 1.1 后(加 industry / coop_term / 等列),`db/init.sql` 更新了,但**已存在的 DB 没跑 ALTER TABLE**。每次 fresh init 才会同步。

**修复**: 写 `scripts/migrate_db_to_v1_1.py`,逐列 `ALTER TABLE ADD COLUMN IF NOT EXISTS`,idempotent — 跑多次安全。一次性执行后 schema 对齐。

**启示**: SQLite `CREATE TABLE IF NOT EXISTS` 不会做 column-level 增量,只判表存在与否。任何 schema 变动都要写显式 migration script — 不要靠 init.sql 的"下次重建" hopeful thinking。考虑引入 alembic 或类似工具(目前规模手写 OK)。

---

## 7. Gemini SDK schema proto 拒收 Pydantic 生成的 JSON Schema 字段

**症状**: 用 `model.generate_content(response_schema=Course.model_json_schema())` 直接抛 `Unknown field for Schema: minLength` / `pattern` / `anyOf`。

**根因**: Pydantic v2 `model_json_schema()` 输出标准 JSON Schema 2020-12,但 google-generativeai SDK 的 `protos.Schema` 只支持子集 — 不收 `minLength`、`pattern`、`additionalProperties`、`anyOf`、`$ref` 等。

**修复**: 写 `pydantic_to_gemini_schema()`(`llm/gemini_client.py:167`):
1. 解 `$ref`(用 `$defs` table 内联)
2. 剥不兼容字段(`_GEMINI_UNSUPPORTED_SCHEMA_KEYS`)
3. 平 `anyOf` 到 `nullable` 形式
4. prune dangling `required` 项
5. context-aware:`title` 既是 schema metadata 又可能是 properties 名(Textbook.title 字段)— 在 properties map 内不剥
6. 处理 `type: ["string", "null"]` 数组类型 → `type: "string", nullable: True`

服务端 Pydantic `schema.model_validate_json(response_text)` 仍然全字段验证,strip 只影响 LLM 输入提示。

**启示**: SDK 的 Schema proto vs JSON Schema 标准是历史不齐的"几乎兼容";直接传 Pydantic schema 在 90% case 工作但会被边角字段坑。为生产可靠性必须有 normalization layer。

**Week 8 §3.5 supplement (2026-05-05 实测)**: google.genai 新 SDK 没救场 — 它把 Pydantic class 转 protobuf 时 emit `additional_properties`(snake_case,跟旧 SDK 拒绝的 `additionalProperties` camelCase 不同字段名,但同类问题),Gemini API 仍 INVALID_ARGUMENT。修复路径相同:走 dict + strip helpers,bypass SDK 自己的 type→schema 转换。`pydantic_to_gemini_schema` 函数因此**未删**,只调整文档定位:从"旧 SDK workaround"升格为"两代 SDK 共用的 normalization 层"。

---

## 8. SQLite CURRENT_TIMESTAMP 跨秒触发 sleep 测试 flake

**症状**: `tests/test_user_courses_schema.py` 里两个 trigger 测试用 `time.sleep(1.1)` 等 SQLite `CURRENT_TIMESTAMP` 进下一秒再 update,验证 `updated_at` 真的变了。CI 重负载下偶发失败 — sleep 1.1s 不足以确保跨秒。

**根因**: SQLite `CURRENT_TIMESTAMP` 默认秒级精度,且依赖系统时钟。`sleep(1.1)` 在系统调度延迟下可能落在同一秒(尤其 Windows / WSL2 hybrid 下时钟精度更松)。

**修复**: 改 deterministic pattern — 先 `UPDATE ... SET updated_at = '2020-01-01 00:00:00'`(seed 一个明确旧时间),触发器跑后 assert `updated_at != '2020-01-01 00:00:00'`。无 sleep,无时钟依赖。

**启示**: 任何"等真实时间过去"的测试都是 flake source。换成 deterministic 输入(注入种子值)+ assert "改变发生"语义,而不是"时间向前"语义。同样的 pattern 适用于 audit 表、event 排序、TTL 测试。

---

## 共同主题

| 主题 | 出现于 | Take-away |
|---|---|---|
| 第三方 UI / SDK 改版无 changelog | #1 (Google Console), #7 (Gemini SDK) | 关键依赖每季重测一次部署文档 |
| 客户端约束 vs 服务端 enforcement 不对称 | #2 (`hd` vs `is_email_allowed`) | 只在一层强制,另一层最多做 hint |
| Path 路由 / 子路径 是历史遗留 | #3 (cloudflared), #4 (Streamlit) | 新部署直接子域,不走 prefix |
| 改配置 → 重启进程的隐式约束 | #5 (settings cache) | 写进 runbook + 考虑一键 restart |
| 增量 schema 变更需要显式 migration | #6 (DB ALTER TABLE) | init.sql 不替代 migration script |
| 时间 / 真实环境的测试不可靠 | #8 (sleep) | 用 deterministic seed 替代时钟 |

---

## 修复后的回归覆盖

- `tests/test_oauth.py` (#1, #2)
- `tests/test_cloudflare_smoke.py` 的双子域路径断言 (#3, #4)
- `scripts/migrate_db_to_v1_1.py` 跑两次仍 idempotent + `tests/test_user_courses_schema.py` 7 条 (#6)
- `tests/test_gemini_client.py` 11 条覆盖 `pydantic_to_gemini_schema` 各分支 (#7)
- `tests/test_user_courses_schema.py` 触发器测试改 deterministic pattern (#8)

测试套件: 624 → 631 passed,零 flake 重跑。
