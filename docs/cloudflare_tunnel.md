# Cloudflare Tunnel · 软启动公开 URL 运维手册 (Week 6)

> 让 3 人团队从公网访问 WSL2 上跑的 FastAPI + Streamlit, 不开端口/不上云的最小方案。
> ADR-0014 决定运行时数据在 WSL home; 此运行时也跑在 WSL2 里, Tunnel 进程是同 host 的 user-level daemon.

---

## 0. 5 分钟决策

**为什么 Cloudflare Tunnel 而不是 ngrok / serveo / 上云?**

| 方案 | 公网 URL | 免费 | F1 合规 | 团队多人共享 | 备注 |
|---|---|:---:|:---:|:---:|---|
| **Cloudflare Tunnel** | ✅ 自定义子域 | ✅ | ✅ | ✅ | 选这个 |
| ngrok 免费版 | ⚠️ 随机变化 | ✅ | ✅ | ❌ 单连接 | 调试用 OK |
| 端口转发 + DDNS | ✅ | ✅ | ⚠️ ISP TOS | ✅ | 暴露 NAT 后端 |
| Cloud (EC2/Fly) | ✅ | ⚠️ | ⚠️ 商业化嫌疑 | ✅ | F1 红线: 不商业化 |

Cloudflare Tunnel 是 outbound-only (WSL → CF edge), NAT/防火墙穿透不需配置, 免费 tier 足够 ≤ 50 RPS 的 MVP.

**最小拓扑** (这文档 cover 的就是这套):

```
公网 https://compass.<your-cf-zone>.com
        │
        ▼
   Cloudflare Edge
        │   (HTTP/2 + 自动 cert)
        ▼  outbound from WSL2
   cloudflared (user-level daemon)
        │
        ├─→ http://localhost:8000  (FastAPI / api.main:app)
        └─→ http://localhost:8501  (Streamlit / app/streamlit_app.py)
```

---

## 1. 前置条件

- 一个 Cloudflare 账户 (免费即可) + 一个绑过的域名 (zone)
  - 没有? `*.trycloudflare.com` 的随机子域可以零配置启动 (见 §5 的 quick tunnel)
- WSL2 Ubuntu 24.04 (本项目标准)
- FastAPI + Streamlit 都跑得起来 (端口 8000 + 8501)

---

## 2. 安装 cloudflared (WSL 内, 一次性)

```bash
# WSL 内, 不需要 sudo 的安装路径
mkdir -p ~/bin
curl -L --output ~/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x ~/bin/cloudflared

# 加到 PATH (放进 ~/.bashrc, 一次)
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 验证
cloudflared --version
```

> 如果你的 ~/.bashrc 已经把 `~/.cargo/bin` 之类加进 PATH, 把 `~/bin` 也并进去就行.

---

## 3. 登录 + 创建 named tunnel

```bash
# 1) 浏览器登录 (会打开 Cloudflare 页面让你选 zone)
cloudflared tunnel login
# 完成后 ~/.cloudflared/cert.pem 存证书

# 2) 建一个有名 tunnel (起个固定名字, 不要随机)
cloudflared tunnel create neu-compass
# 输出 tunnel UUID, 记下来或看 ~/.cloudflared/<UUID>.json

# 3) 绑定子域 (把 compass.<your-zone>.com 指向这个 tunnel)
cloudflared tunnel route dns neu-compass compass.<your-zone>.com
```

---

## 4. 配置文件

把下面写进 `~/.cloudflared/config.yml`:

```yaml
tunnel: neu-compass
credentials-file: /home/<your-wsl-user>/.cloudflared/<tunnel-uuid>.json

ingress:
  # 主入口 → Streamlit (用户实际看的页面)
  - hostname: compass.<your-zone>.com
    service: http://localhost:8501
    originRequest:
      # Streamlit 用 websocket 做实时 rerun, 必须开
      noTLSVerify: false
      connectTimeout: 30s
      tcpKeepAlive: 30s

  # 子路径 /api → FastAPI (Streamlit 内部也通过这条访问)
  - hostname: compass.<your-zone>.com
    path: ^/api/.*$
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s

  # 兜底 (cloudflared 要求最后一条 catch-all)
  - service: http_status:404
```

重要:
- `path` 用 regex 匹配, 把 `/api/...` 转给 FastAPI 而不是 Streamlit
- `originRequest.noTLSVerify` 保持默认 false; 我们 origin 是 plain http (localhost), CF edge 自动加 https
- 不要把 `service` 写成 `0.0.0.0:8000`, 写 `localhost`, 否则 WSL 的 9P 网络栈偶尔会绕到 Windows host 端口

---

## 5. 启动 + 烟囱测试

```bash
# 一次性 quick tunnel (不需要 zone, 给个随机 *.trycloudflare.com)
cloudflared tunnel --url http://localhost:8501
# 输出:
#   2026-... INF +-----...
#   2026-... INF | Your quick Tunnel has been created! Visit it at:
#   2026-... INF |   https://random-words-xxxx.trycloudflare.com
# 适合: 5 分钟内给一个同学发链接试一下

# 长期 named tunnel (用 §3 + §4 配置)
cloudflared tunnel run neu-compass
# 启动后 compass.<your-zone>.com 就活了
```

按 ctrl-C 停, 重启不会丢域名绑定 (route dns 是持久的).

---

## 6. 跟 Streamlit / FastAPI 一起跑

3 个 terminal (或 tmux 分屏):

```bash
# Terminal 1 - FastAPI (会 lock 住, 70s 模型预热, 然后接收请求)
cd /mnt/h/neu-compass
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 - Streamlit
cd /mnt/h/neu-compass
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Terminal 3 - cloudflared
cloudflared tunnel run neu-compass
```

**Streamlit 必须 `--server.address 0.0.0.0`**, 默认 127.0.0.1 不接受来自 cloudflared 进程的连接 (在某些 WSL 网络模式下).

---

## 7. 健康检查 + 烟囱

启动后:

```bash
# 1) 进程内 (本地)
curl -s http://localhost:8000/health   # → {"status":"ok"}
curl -s http://localhost:8000/ready    # → {"status":"ready", ...}
curl -s http://localhost:8501          # → Streamlit HTML

# 2) 边缘 (公网)
curl -s https://compass.<your-zone>.com/api/health
curl -s https://compass.<your-zone>.com/api/ready
curl -s https://compass.<your-zone>.com -o /dev/null -w "%{http_code}\n"  # 200
```

如果 /ready 返回 `{"status": "warming"}`, 等 70s (bge-m3 cold start, PLAN_v2.0 §2.5).

---

## 8. 常见故障

| 症状 | 排查 |
|---|---|
| `Error 1033 Argo Tunnel error` | cloudflared 进程没在跑, 或 config.yml 里的 tunnel 名/UUID 错了 |
| `502 Bad Gateway` 经过 CF 但本地 200 | Streamlit 用了 127.0.0.1 而不是 0.0.0.0; 改 `--server.address 0.0.0.0` |
| `WebSocket handshake failed` | Streamlit rerun 用 ws; 检查 ingress 里没有错误的 noTLSVerify; `cloudflared tunnel info <name>` 看 active connections |
| 前端 404, /api/* 也 404 | path regex 写错了, ingress 顺序也很重要 (path 规则要在 catch-all hostname 规则前面) |
| 502 偶发 | uvicorn 的 70s 冷启动期间; `/ready` 是 warming. 加一个 systemd timer 提前预热 (Week 7) |

---

## 9. F1 合规备忘

- **不要在 Tunnel 上接收付款回调** — PLAN §9 红线
- **OAuth redirect URL 必须是这个 Tunnel 子域** — Google Cloud Console 里改
  `https://compass.<your-zone>.com/oauth/callback`
- **API key 不要硬编码进 config.yml** — 这文件会被 git 跟 (但 `.cloudflared/<uuid>.json` 在 ~ 不在 repo, 安全)
- **公网开放期间, 监控 401/403 比例**: structlog 的 access log 已经记每个请求, 看 grafana / 直接 grep `request.handled` 行
- **关停**: 软启动结束直接 `cloudflared tunnel cleanup neu-compass` + `cloudflared tunnel delete neu-compass` 解绑

---

## 10. 下一步 (Week 7+)

- systemd unit 把 cloudflared 做成开机自启
- pre-warm hook 把 ready 时间从 70s 缩短 (改 BGEM3 模型放在共享 volume, 跨进程 mmap)
- Cloudflare Access 加 SSO 网关, 限定 husky.neu.edu 才能访问页面 (双层防护: app/auth.py 的 OAuth + CF Access)
- 真实 query log 收齐后做 PromQL/Grafana 看板

---

## 11. Windows + WSL2 部署变体 (PLAN v2.2 §3.1 实测)

> 本项目代码 / 数据走 WSL (ADR-0014) 但开发主机是 Windows 11。
> 把 cloudflared 装在 Windows 边、跨 WSL 边界连服务,比在 WSL 里再装一份
> 简单 —— 单进程, 不需要 systemd, 重启 WSL 不影响 Tunnel 在线。

### 11.0 实测 deploy 状态 (2026-05-04 落地)

> **Tunnel UUID**: `ce52553f-7fc3-48dc-923d-3dd9ea772f06`
> **Domain**: `neu-compass.me` (CF Registrar 外购 → NS 改为 bella+salvador.ns.cloudflare.com)
> **公网映射**:
> - `https://api.neu-compass.me` → `localhost:8000` (FastAPI canonical)
> - `https://compass.neu-compass.me` → `localhost:8501` (Streamlit + OAuth callback)
> **Apex `neu-compass.me`**: 留给 CF 自动页(zone 创建时已有 A/CNAME,Tunnel route 拒覆盖,改用子域更简单)
>
> 历史决策 (踩坑记录):
> - 初版 config 用单域 + path 规则 (`/api/*` → 8000) — 失败,因为 cloudflared 没有 path-rewrite
>   能力,uvicorn 收到 `/api/health` 找不到路由(它的路由在 `/health`)。
> - 切到双子域 `api.* / compass.*`,FastAPI 不需任何 prefix 改动。

### 11.1 已完成 (Week 7 sprint)

```powershell
# Windows PowerShell / cmd, winget 可用
winget install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements
# → C:\Users\<you>\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_*\cloudflared.exe
# 已自动加 PATH (新窗口生效);当前窗口先 refreshenv 或重开
cloudflared --version
```

实测 2025.8.1 装好后,Windows cmd 任何新会话都能直接 `cloudflared`。

### 11.2 Windows 边缘网络: WSL2 服务可达性

WSL2 默认 `mirrored` 网络模式 (Win 11 22H2+) 把 WSL 内 0.0.0.0 端口
**直接映射到 Windows localhost**, 所以 Windows 上的 cloudflared 跑
`localhost:8000` / `localhost:8501` 是可以连到 WSL 内 uvicorn / streamlit 的。
若使用旧的 NAT 模式, 改成连 `wsl hostname -I` 输出的 IP (172.x.x.x)。

验证 (启 uvicorn 后, Windows PowerShell 里):

```powershell
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
# StatusCode: 200, Content: {"status":"ok"}
```

### 11.3 Windows 端 config.yml

文件位置: `%USERPROFILE%\.cloudflared\config.yml` (即 `C:\Users\<you>\.cloudflared\config.yml`)。
登录证书 (`cert.pem`) 和 tunnel 凭证 JSON 也都落在该目录。

模板 (登录 + create tunnel 后填空):

```yaml
tunnel: neu-compass
credentials-file: C:\Users\<your-windows-user>\.cloudflared\<tunnel-uuid>.json

ingress:
  # 主入口 → Streamlit (debug-only;v2.2 §3.3 把它降级了)
  - hostname: compass.<your-zone>.com
    service: http://localhost:8501
    originRequest:
      noTLSVerify: false
      connectTimeout: 30s
      tcpKeepAlive: 30s

  # /api/* → FastAPI (Andy 前端 + curl 调 API 走这条)
  - hostname: compass.<your-zone>.com
    path: ^/api/.*$
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s

  # 兜底
  - service: http_status:404
```

### 11.4 你下一步要做的 (按顺序)

1. **登录 Cloudflare** (浏览器交互):
   ```powershell
   cloudflared tunnel login
   ```
   选你的 zone, 完成后 cert.pem 落地。

2. **创建 named tunnel**:
   ```powershell
   cloudflared tunnel create neu-compass
   # 输出 UUID, 写入 ~/.cloudflared/<uuid>.json
   ```

3. **绑定子域** (zone 必须是你已经在 CF 托管的域):
   ```powershell
   cloudflared tunnel route dns neu-compass compass.<your-zone>.com
   ```

4. **填 config.yml** (用上面 §11.3 模板,把 `<your-windows-user>` /
   `<tunnel-uuid>` / `<your-zone>` 替换)。

5. **配 Google OAuth Console** (https://console.cloud.google.com/):
   - OAuth 2.0 Client ID → Authorized redirect URI 加:
     `https://compass.<your-zone>.com/oauth/callback`
   - Client ID + Secret 复制到 `.env`:
     ```
     GOOGLE_OAUTH_CLIENT_ID=<...>
     GOOGLE_OAUTH_CLIENT_SECRET=<...>
     API_BASE_URL=https://compass.<your-zone>.com/api
     ```

6. **三窗口起服务** (前两在 WSL, 第三在 Windows):
   ```bash
   # WSL terminal 1
   wsl -d Ubuntu-24.04
   cd /mnt/h/neu-compass
   uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

   # WSL terminal 2
   wsl -d Ubuntu-24.04
   cd /mnt/h/neu-compass
   uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0
   ```
   ```powershell
   # Windows terminal 3 (cmd 或 PowerShell)
   cloudflared tunnel run neu-compass
   ```

7. **冒烟** (uvicorn 起来 ~70s 模型预热后):
   ```powershell
   curl https://compass.<your-zone>.com/api/health
   # {"status":"ok"}
   curl https://compass.<your-zone>.com/api/ready
   # {"status":"ready","courses_indexed":6469,"bm25_corpus":6469}
   ```

8. **发给团队** (LYU / Andy / Yuang):
   ```
   公网 URL: https://compass.<your-zone>.com
   API:     https://compass.<your-zone>.com/api
   契约:    docs/api_contract.md (见 repo)
   说明:    走 Google 登录, 必须 husky.neu.edu / northeastern.edu 邮箱
   要求:    每人跑 ≥ 5 query (达 KPI ≥ 200 真 query)
   ```

KPI 满足条件 (PLAN §2.1):
- 公网 URL 200 ✓
- ≥ 5 contributors OAuth round-trip
- ≥ 200 真 query (`grep request.handled api.log | wc -l`)

### 11.5 Windows-端 故障速查

| 症状 | 看哪儿 |
|---|---|
| `cloudflared` 命令不存在 | 重开 cmd / PowerShell;新窗口才有 PATH |
| 公网 200 但本地访问也 200 一样的页面 | 路由配置反了:Streamlit 应在 hostname 兜底,FastAPI 在 `/api/*` |
| 公网 502 | uvicorn 没启动 OR 仍在 70s 冷启动;`curl localhost:8000/ready` 看是否 `warming` |
| 公网通 但 OAuth 拒绝 | Google Console redirect URI 没加 https:// 公网那条;或 .env 的 `GOOGLE_OAUTH_CLIENT_ID` 跟 console 不一致 |
| WSL 服务 Windows 访问不到 | WSL 网络模式; `wsl --status` 看 `networkingMode`. 不是 `mirrored` 就改成 `localhost-forwarding=true` 或用 `wsl hostname -I` 的 IP |
