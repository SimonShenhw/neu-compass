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
