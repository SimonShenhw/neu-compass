# Runbook · OAuth Client Secret Rotation

> **目的**: rotate `GOOGLE_OAUTH_CLIENT_SECRET`(Google OAuth 2.0 client secret),把当前在 chat / 截图里 leak 过的 secret 作废。
> **场景**: PLAN v2.3 §3.8 — Week 7 部署期间 secret 截图在 chat 暴露过(虽然概率低,视为已暴露)。
> **预估时间**: 5 分钟(Console 操作 + 重启 uvicorn)。
> **要求**: 你能登录 Google Cloud Console 的 owner / admin 账号 + 有 WSL2 + .env 写权限。

---

## 0. 安全前提(必读)

- **rotate 不影响已登录用户**:OAuth client_secret 只在 token exchange (`POST /auth/callback`) 时用,**access token / id token 一旦签发就跟 secret 解绑**。已登录 session 不会失效。
- **rotate 影响"换 token"和"刷新 token"**:用旧 secret 跑 token exchange 会立即 401。生产实测窗口期(从 Console 改完到 .env 改完 + uvicorn 重启)期间任何**新登录**会失败 → 选低峰期或维护窗口操作。
- **新 secret 在 Console 上是 plaintext**,只能复制一次 — 复制后立即写 .env,不要先存到任何地方(剪贴板算最低暴露)。

---

## 1. 操作步骤

### 1.1 Google Cloud Console rotate

1. 打开 [https://console.cloud.google.com/](https://console.cloud.google.com/) → 切到 NEU-Compass project
2. 左侧 **APIs & Services** → **Credentials**
3. 找到 OAuth 2.0 Client IDs 里你的 client(name: 应该是 "neu-compass" 或类似)→ 点进去
4. 顶部右上找 **"Reset Secret"** 按钮(2026 UI 在 client 详情页顶部 action bar)
   - 旧 UI 路径: 详情页 → "Add Secret" → 新建后再 "Disable" 旧的
5. 弹窗 confirm "Reset" → 显示新 secret(一次性,复制立即用)
6. **保留浏览器页面打开**,不要关 — 万一 .env 写错可以 fallback

### 1.2 写入 WSL .env

```bash
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
```

编辑 `.env` 文件(不要 `cat` 出来 — 会写到 shell history):

```bash
# 用 nvim / vim 之类的避免 shell history 暴露
nvim .env
```

把这行替换:
```
GOOGLE_OAUTH_CLIENT_SECRET=<旧值>
```
为:
```
GOOGLE_OAUTH_CLIENT_SECRET=<新值,从 Console 粘贴>
```

保存退出。**不要 `git diff .env`** — `.env` 在 `.gitignore` 里,但 `git diff` 会把新 secret 渲到终端 buffer。

### 1.3 重启 uvicorn(WSL terminal 1)

```bash
# 找到 uvicorn 进程
ps -ef | grep uvicorn
kill <pid>

# 或如果是用 trap 的 wrapper:
# pkill -f "uvicorn api.main:app"

# 重起
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
# 等 ~70s lifespan 预热(bge-m3 + reranker 加载)
# 看到 "Application startup complete" + /ready 返回 200 才算真起来
```

### 1.4 重启 Streamlit(WSL terminal 2)— **必做**

> **Week 7 §9.5 踩坑**:`config.settings` 是 lru_cache 单例,Streamlit 边也持有自己的 cache。
> 只重启 uvicorn 不够 — Streamlit 边发 authorize_url 用旧 secret 路径，会出现"authorize 时 redirect_uri 跟 token 时 不一致" 的 invalid_grant 错误。

```bash
ps -ef | grep streamlit
kill <pid>
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0
```

### 1.5 (可选)cloudflared 重启 — 通常**不需要**

cloudflared 不读 `.env`,只做 L7 反向代理。除非:
- 你之前 hardcode 过 secret 进 `~/.cloudflared/config.yml`(不应该)
- 跨 WSL 边界的 mirrored 网络在重启进程时丢连接(实测 mirrored 模式重连 ~2s)

---

## 2. 验证

### 2.1 旧 secret 应该 401

```bash
# 模拟旧 secret 调 Google token endpoint(不通过我们的 API,直接打 Google)
# 注意: 这里用 dummy code,只是看 Google 接受/拒绝 secret
curl -i -X POST https://oauth2.googleapis.com/token \
  -d "client_id=$GOOGLE_OAUTH_CLIENT_ID" \
  -d "client_secret=<旧 secret>" \
  -d "code=fake" \
  -d "grant_type=authorization_code" \
  -d "redirect_uri=https://compass.neu-compass.me/"

# 期望: HTTP 401 with {"error": "invalid_client"}
# 这表示 Google 已经把旧 secret 作废
```

### 2.2 新 secret 完整 round-trip

```bash
# 浏览器打开 https://compass.neu-compass.me/
# 点 "Login with Google"
# 用 husky.neu.edu 邮箱登
# 应该 round-trip 成功,sidebar 显示 user.email
```

后端 log 看:
```bash
# WSL terminal 1 uvicorn 输出里应该看到:
# {"event": "auth.callback.success", "user_sub": "...", ...}
```

### 2.3 失败回滚

如果新 secret 不工作 → Console 页面还在 §1.1 第 6 步打开 → 可以再点一次 Reset 拿第二份新 secret 重来。
**不要回滚到旧 secret** — 它已经在 Console 上 disabled,任何旧值都失效。

---

## 3. 后续

### 3.1 Audit 旧 secret 是否真的 leak 了

- 翻 chat history / Slack / Lark 看 Week 7 部署期间是否有 secret 字符串(15+ 字符,通常 `GOCSPX-` 前缀)
- 如果**确认 leak**:除 rotate 外,看 Google Cloud Console → IAM & Admin → Audit Logs,过滤 `oauth2.googleapis.com` API call,看是否有非预期 IP / 非预期时间窗的 token exchange
- 如果**只是怀疑 leak**(本 SOP 默认场景):rotate 即可,无需 audit

### 3.2 更新 incident 记录

- `docs/postmortem_week7.md` 已经覆盖部署期间的 8 类踩坑;secret leak 不在其中(单独事项)
- 在私人 incident log 里记一笔(项目级 incident.md 不入 git,F1 合规):
  ```
  2026-05-05 secret rotation
  - Cause: client_secret 截图在团队 chat 暴露过(.env 操作截图)
  - Action: rotate via Console + restart uvicorn + streamlit
  - Verify: 旧 secret 401, 新 secret round-trip 通
  - Followup: 后续部署文档不再贴 .env 截图,改文字 redact (xxxxx)
  ```

### 3.3 预防

- README / `.env.example` / 任何文档里**禁止贴真 secret 占位符** — 用 `your_oauth_client_secret` 而非看起来像真值的字符串
- 截图 .env 时**先 redact** — 用 macOS Preview / Snipping Tool 的黑色矩形涂掉
- pre-commit `detect-secrets` 严格模式已经覆盖 commit 时的检测;chat / 截图层面靠纪律

---

## 4. 参考

- Google Cloud OAuth 2.0 client secret rotation 官方:[https://support.google.com/cloud/answer/15549257](https://support.google.com/cloud/answer/15549257)
- 项目本地实现:[app/auth.py](../app/auth.py) `exchange_code_for_token`
- 配置层:`config.settings.google_oauth_client_secret` (pydantic-settings,lru_cache 单例)
- F1 合规红线:`PLAN_v2.3.md` §1 + `README.md` §红线
