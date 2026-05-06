# SOP · Streamlit chat_input WebSocket / 视觉问题排查

> **目的**: 复测 Week 7 §3.9 报告 — 公网部署后 Streamlit chat_input "看起来灰",不确定是 视觉默认 / WebSocket 失败 / Cloudflare 升级配置问题。
> **预估时间**: 30 分钟(本机 + 浏览器 F12)~ 2 小时(若需改 cloudflared 配置)。
> **前置**: 服务都跑得起来(`/health` 200, `/ready` ready),浏览器能打开 `https://compass.neu-compass.me/`。

---

## 0. 决策树(快速分类)

```
Streamlit 页面打开 → chat_input 灰显
        │
        ├─ 输入框完全无响应,鼠标点击无 cursor
        │   → §1 (Streamlit 自身视觉默认 OR DOM 渲染失败)
        │
        ├─ 输入框有 cursor 能输入,但提交 (Enter / Send) 无反应
        │   → §2 (WebSocket / API call 失败)
        │
        ├─ 提交后页面卡在 "thinking..." 不返回 token
        │   → §3 (NDJSON stream 中断 / cloudflared WS 升级问题)
        │
        └─ 字段灰 + Console 报 CSP / 401 / CORS
            → §4 (auth / 跨域 / CSP 问题)
```

---

## 1. Streamlit 自身视觉默认 / DOM 渲染

### 1.1 排查

打开 `https://compass.neu-compass.me/` → F12 → Console → Elements:

```javascript
// 在 Console 跑:
document.querySelector('[data-testid="stChatInput"]')
// 期望: <div ...> 真实 DOM 节点
// 如果返回 null → Streamlit 没渲染到 chat_input,组件加载失败
```

```javascript
// 看灰显是不是 disabled 属性
document.querySelector('[data-testid="stChatInput"] input').disabled
// true → 输入框真的 disabled(可能是 auth gate 没过 / state 没就绪)
// false → 视觉灰但功能在
```

### 1.2 已知 Streamlit chat_input 视觉默认

Streamlit ≥ 1.30 的 `st.chat_input` 默认 placeholder text 颜色 `#888` (mid-gray),
跟周围背景 `#fafafa` 差距小,**视觉上"看起来 disabled"** 但实际可用。

```bash
# 看运行中的 Streamlit 版本
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/h/neu-compass && uv run python -c "import streamlit; print(streamlit.__version__)"'
```

| Streamlit | chat_input 视觉 |
|---|---|
| 1.28-1.31 | 默认 mid-gray placeholder + 浅边框,易误认 disabled |
| 1.32+ | placeholder 加粗 + 加深,改善 |

### 1.3 修复 / 缓解

**短期**(不升 Streamlit):在 `app/streamlit_app.py` 顶部加 CSS override:

```python
import streamlit as st

st.markdown("""
<style>
[data-testid="stChatInput"] {
    border: 2px solid #4a90e2 !important;
    background: #ffffff !important;
}
[data-testid="stChatInput"] input::placeholder {
    color: #444 !important;
    font-weight: 500 !important;
}
</style>
""", unsafe_allow_html=True)
```

**中期**: `pyproject.toml` 升 streamlit ≥ 1.32(需测 OAuth flow + chat_input 兼容性,Week 8 后空档)。

---

## 2. WebSocket 失败

Streamlit 用 `_stcore/stream` WebSocket 跟 server 同步 widget state。
WS 失败 → 输入框灰 + 提交无响应 + Console "Disconnected" 红条。

### 2.1 浏览器 F12 验证

F12 → **Network** tab → 上方 filter 选 **WS** → 刷新页面:

| 期望 | 实测 | 含义 |
|---|---|---|
| `_stcore/stream` Status **101** Switching Protocols | ✅ | WS 升级成功 |
| `_stcore/stream` Status **200** | ❌ | cloudflared 没升级 WS,只发了 HTTP |
| `_stcore/stream` Status **502 / 503** | ❌ | cloudflared 到 streamlit 的 connection 断了 |
| 没 `_stcore/stream` 请求 | ❌ | Streamlit 没尝试 WS — 可能 JS bundle 没加载 |

### 2.2 cloudflared WS 升级配置

我们 `~/.cloudflared/config.yml` 现在(Week 7 §3.1)的 `originRequest`:

```yaml
ingress:
  - hostname: compass.neu-compass.me
    service: http://localhost:8501
    originRequest:
      noTLSVerify: false       # origin 是 plain HTTP localhost,正确
      connectTimeout: 30s
      tcpKeepAlive: 30s
```

**WS 升级是 cloudflared 默认开**(`http2Origin: false` 时自动 HTTP/1.1 + Upgrade),
但**长连接超时**会偷偷 kill WS:

```yaml
# 在 originRequest 加这两条
originRequest:
  noTLSVerify: false
  connectTimeout: 30s
  tcpKeepAlive: 30s
  noHappyEyeballs: false      # 默认就 false
  keepAliveTimeout: 90s        # 默认 90s,可显式写出方便审计
  keepAliveConnections: 100    # 默认
  proxyConnectTimeout: 30s
  # ↓ 关键:WS 长连接超时
  disableChunkedEncoding: false  # 不要 disable, WS 需要
```

测试改完后:
```bash
# Windows terminal:
cloudflared tunnel --loglevel debug run neu-compass 2>&1 | grep -E "Upgrade|WebSocket|websocket"
# 应该看到 "Upgrading connection to WebSocket" 日志
```

### 2.3 Streamlit `--server.address 0.0.0.0` 必须

Week 7 §3.1 实测踩过:`127.0.0.1` 监听时,WSL2 mirrored 模式 + Windows cloudflared 偶发 502。

```bash
# 必须 0.0.0.0
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0
```

### 2.4 Streamlit `--server.enableCORS=false` (公网部署可选)

Streamlit 1.30+ 对跨域 WS 升级有 CSRF check。Cloudflare 边代理后 origin 头变,
某些版本会拒。如果 §2.1 看到 WS 直接 close 而无 101,试:

```bash
uv run streamlit run app/streamlit_app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
```

**安全权衡**: 关 XSRF 把 attack surface 扩到"任何站点能 POST 到 8501 widget endpoint"。
但我们前面有 cloudflared + Google OAuth + `is_email_allowed` 三层,可接受。
Production 上 React 前端时这个不是问题(从根本不用 Streamlit)。

---

## 3. NDJSON stream / `/chat` 路径中断

输入框可用、提交后卡 "thinking..." 不出 token → 是 `/chat` 流问题不是 widget 问题。

### 3.1 验证 `/chat` 直接通

绕过 Streamlit,直接 curl:

```bash
curl -N -X POST https://api.neu-compass.me/chat \
  -H "Content-Type: application/json" \
  -d '{"q": "what is AAI 6600?"}'
# -N = no buffering,看 NDJSON 一行一行出
# 期望: {"type": "meta", ...}\n{"type": "token", "text": "AAI"}\n... {"type": "done"}
```

| 实测 | 含义 |
|---|---|
| 完整 NDJSON 顺序流 | ✅ 后端没问题,Streamlit consumer 端 bug |
| 卡很久最后一次性吐出 | cloudflared buffer 了 stream(看下面 §3.2) |
| 直接 5xx | uvicorn 或 Gemini call 失败 — 看 uvicorn log |

### 3.2 cloudflared 不 buffer stream

NDJSON / SSE 不能被边缘 buffer,否则 stream UX 完全坏。`originRequest` 加:

```yaml
originRequest:
  noChunkedEncoding: false   # 必须 false,允许 chunked
  http2Origin: false         # HTTP/1.1 + chunked 比 H2 更稳(实测)
  disableChunkedEncoding: false
```

### 3.3 Streamlit `st.write_stream` 消费

`app/streamlit_app.py` 里 `st.write_stream(stream_assistant(...))` 要求 generator 直接 yield string。
如果 generator 内部 catch 了 exception 后 `return` 而不是 raise:

```python
# 错的:exception 吃了,UI 卡住
def stream_assistant(prompt):
    try:
        for chunk in api_client.chat_stream(prompt):
            yield chunk["text"]
    except Exception:
        return  # ← UI 不知道发生了什么

# 对的:propagate 让 Streamlit 显示错误
def stream_assistant(prompt):
    for chunk in api_client.chat_stream(prompt):
        yield chunk["text"]
```

---

## 4. Auth / CORS / CSP 边界

如果灰显伴随 Console 红:

| Console 红 | 修 |
|---|---|
| `401 from /api/...` | OAuth round-trip 没完成,session 没建立。先验 §3 OAuth flow 通 |
| `CORS preflight failed` | 前后端不同 origin 时;我们目前 streamlit 走自己 8501 + 调 8000,不跨 origin。真出现 → 看 cloudflared 是否双子域跨 origin |
| `Refused to load script ... CSP` | Streamlit 的 CSP 默认很严;`unsafe_allow_html=True` 注入的内容可能被拦 |
| `Mixed Content: HTTP loaded over HTTPS` | API_BASE_URL 仍是 `http://localhost:8000`(配置反 — 应该公网走 `https://api.neu-compass.me`)|

---

## 5. Acceptance(完成本 SOP 视为通过)

- [ ] §2.1 F12 Network 看到 `_stcore/stream` Status 101 Switching Protocols
- [ ] chat_input 接受输入(光标 + 文字进入)
- [ ] 提交后 uvicorn log 见 `chat.completed` 事件
- [ ] Streamlit `st.write_stream` 渲染 token 流(不是一次性 dump)
- [ ] 如果以上都过但视觉仍灰 → 写进 README known-limitations,不阻塞 ship

---

## 6. 兜底:已知 limitation

如果 §1-§4 都过了,chat_input 视觉仍 "看起来灰":

1. 这是 Streamlit 1.X 默认 placeholder 视觉,**不是 bug**
2. 真正的 product UI 是 Andy Dong 的 React 前端(v3.0+)— 不修复本地 Streamlit
3. 在 README 明确标:"Streamlit UI 是 debug + OAuth landing,product UI 见 compass-frontend"
4. PLAN v2.3 §3.9 acceptance: 30 min 排查 + 记 known limitation,不深修

---

## 7. 参考

- Streamlit chat_input 文档: https://docs.streamlit.io/library/api-reference/chat/st.chat_input
- Cloudflare WS 升级: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/configuration-file/#origin-configuration
- 项目 cloudflare runbook: [docs/cloudflare_tunnel.md](cloudflare_tunnel.md) §11
- 后端 chat NDJSON 实现: `api/routes/chat.py` + `llm/gemini_client.py:generate_text_stream`
