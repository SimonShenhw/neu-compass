# NEU-Compass · PLAN v3.0 (Week 9+ active sprint plan)

> **Updated**: 2026-05-06
> **Previous**: [docs/PLAN_v2.3.md](PLAN_v2.3.md) (Week 8 sprint, shipped),[docs/PLAN_v2_3_1.md](PLAN_v2_3_1.md) (Week 8 hardened review, shipped)
> **Purpose**: Week 9+ forward sprint。**项目相位转移**:从 "engineering ship" 阶段进入 "operational + signal collection" 阶段。Week 9 perf 优化已完成实测(详见 `docs/perf_week9_results.md`)。
> **Read order if you're a fresh agent**: §0 → §1 → §2 → §3 → §6.1 → §8 → §9。

---

## 0. What changed from v2.3.1

v2.3.1 sprint(Week 8 hardened review)**全部 engineering 项目 ship 完毕**。Week 9 加做了 perf 实测,把 ONNX/TRT 路径走完(详见 `docs/perf_week9_results.md`)。

| Sprint | 状态 |
|---|---|
| v2.2 (Week 7) | ✅ shipped(public soft-launch + ADR-0015/0016) |
| v2.3 (Week 8) | ✅ shipped(prompt v1.1 + SDK migrate + portfolio) |
| v2.3.1 (Week 8 hardening) | 🟡 partial — KPI 1-4 ship,KPI 5(traffic outreach)未启动 |
| **Week 9 perf**(Day 1 + 2) | ✅ shipped(ONNX backend ship,实测完成) |

**v3.0 phase shift**:
1. **代码主线 ship 完毕**:engineering 工作量从 ~5-8h/sprint 降到 ~1-2h(只剩 NAS 部署 + 配置调优)
2. **真 traffic 是阻塞**:KPI 5 outreach + §3.1 v0.3 expansion 等真 user 跑 query;没真数据,§3.2 / §3.6 / §3.10 都不能继续
3. **新硬件目标**:UGREEN NAS DXP6800 Pro 24/7 部署(i5-1235U + Iris Xe iGPU)
4. **触发条件驱动**:v3.0 不再按周做 sprint plan,改"信号触发"模式 — 真 query 累到阈值才动 ADR re-sweep / Ragas / learnable blending

v2.3 / v2.3.1 还 alive 的项目(§3.9 Streamlit WS verify、§3.1-3.10 真 traffic 类)**全部并入 v3.0**;v2.3.1 KPI 5 traffic outreach 升 v3.0 §3.1 P0。

---

## 1. v2.3 invariants still in force

[ADR-0001 / 0013-0016] / k=2 anonymity / OAuth domain / F1 红线 / 测试 floor 全部不变。详见 `docs/PLAN_v2.3.md` §1。

**新增 invariant** (Week 9 perf 实测后):
- **`rag/onnx_backend.py` 是 ship-ready 的二级 backend**;`INFERENCE_BACKEND=onnx + ONNX_PROVIDERS=CUDAExecutionProvider` 在 RTX 5090 cu130 上 startup 11x 快(70s → 6s)
- **`torch.compile` 路径 deprecated** for this user's hardware:Blackwell sm_120 + FlagEmbedding 1.4 hang,在 v3.0 不要再尝试
- **`TensorrtExecutionProvider` 路径 blocked**:ORT 1.25 cu12 build 跟 user cu130 ABI 不兼容,等 ORT 1.26+ 出 cu13 build
- **测试 floor**: `uv run pytest tests/ -q` 必须 ≥ 679 passed (Week 9 ship 数)

---

## 2. v3.0 sprint goals

### 2.1 KPIs (acceptance criteria)

v3.0 ships when **all of these are met OR explicit "wait" decisions documented**:

| # | KPI | 触发条件 / 阈值 | 当前状态 |
|---|---|---|---|
| 1 | NAS 24/7 部署 + OpenVINO EP 实测 | UGREEN DXP6800 Pro 到货 + scp ONNX | 🟡 等硬件到货 |
| 2 | 真 query log ≥ 100 条(test_set v0.3) | KPI 5 outreach 触发 | ⬜ 等 traffic |
| 3 | ADR-0015 + 0016 在 v0.3 上重 sweep | 等 KPI 2 | ⬜ 等 v0.3 |
| 4 | Ragas eval real Gemini judge | 等 KPI 2 | ⬜ 等 v0.3 |
| 5 | Streamlit WS F12 复测 + chat_input 视觉修 | 任何时候(30 min user 操作) | ⬜ 等 user 浏览器 |

KPI 1 是 v3.0 唯一 active engineering 项目。其他全部 signal-driven。

### 2.2 Out of scope (v4.0+)

延续 v2.3 §2.3 全部 deferral,加上:
- ❌ TensorRT EP 路径 — 等 ORT cu13 build(可能 2026 Q3+)
- ❌ FP8 / FP4 量化 — encoder model 收益未验证,工具链 maturing
- ❌ torch.compile + FlagEmbedding — known incompatibility,不再尝试
- ❌ multi-vector ColBERT 第三 leg — 等 ≥ 500 真 query log
- ❌ 社交层 endpoint — 等 ≥ 30 真用户

### 2.3 Budget & quota

| 项 | calls / 资源 | 单价 | 小计 |
|---|---:|---:|---:|
| §3.1 NAS 部署 verify probe | 1 hr 实操 | 0 | 0 |
| §3.2 v0.3 标注 + sweep | 100 query × 0.05 (ragas judge) | $0.01-0.05 | ~$5 |
| §3.4 Ragas eval | 100 × judge | $0.01 | $1 |
| **Total v3.0 月预算** | | | **< $10** |

NAS 24/7 power: ~5W idle / ~25W active × 720h = ~7-15 kWh/月 ≈ ~$1-2 电费。可以忽略。

### 2.4 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NAS 部署 OpenVINO EP 不工作 | M | KPI 1 miss | fallback to CPU EP(慢但 work) |
| ONNX 文件 (2.2 GB) scp 到 NAS 慢 | L | 1-2 min 等待 | 10GbE NAS 网络足够 |
| 真 query 数 < 100 by EOQ | H | KPI 2-4 miss | "wait + outreach" 是 acknowledged stance |
| ORT 出 cu13 build 比预期晚 | M | TRT EP 永远 unreachable on user hardware | accept — CUDA EP 已经够 |
| Andy 的 React 前端永远不落地 | M | Streamlit 一直是 product UI | KPI 5 (Streamlit polish) 是 hedge |

---

## 3. v3.0 task list (priority-ordered)

### 3.1 P0: NAS 24/7 部署(KPI 1)

**前置**: UGREEN DXP6800 Pro 到货 + 装好 UGOS / Ubuntu / Docker。

```bash
# 在 NAS 上(SSH 进 UGOS Container 或 Ubuntu VM)
git clone https://github.com/SimonShenhw/neu-compass.git
cd neu-compass
uv venv
uv sync --extra onnx

# 关键:换 ORT GPU 版为 OpenVINO 版
uv pip uninstall onnxruntime-gpu
uv pip install onnxruntime-openvino

# 验证
uv run python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# 期望: ['OpenVINOExecutionProvider', 'CPUExecutionProvider']

# 从台式机 scp ONNX 文件(2.2 GB)
scp -r ~/neu-compass-data/onnx/ user@nas:~/neu-compass-data/

# .env 配置
cat > .env <<EOF
GEMINI_API_KEY=...           # 从 console 重新拿
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
INFERENCE_BACKEND=onnx
ONNX_MODEL_DIR=/home/<user>/neu-compass-data/onnx
ONNX_PROVIDERS=OpenVINOExecutionProvider
ENABLE_RERANKER=true        # 8 GB RAM 够,可选 false 省 600 MB
EOF

# 起 uvicorn(systemd unit 推荐)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# probe
uv run python scripts/probe_inference_latency.py --label nas-openvino --n 50
```

**Acceptance**:
- /ready 返回 200 + courses_indexed=6469
- p50 < 200ms(target,实测如果 < 150ms 是惊喜)
- 24/7 跑 1 周不挂(systemd auto-restart)
- Cloudflare Tunnel 在 NAS 上跑(or stay on 台式机 + LAN proxy)

ETA: 半天 — 1 天(看 NAS 上手 / Docker / network 顺不顺)。

### 3.2 P0: 真 query log → test_set v0.3(KPI 2)

**触发条件**: 真 query 累到 30+(via team outreach: LYU / Andy / Yuang / 其他)。

参考 v2.3 §3.1 + v2.3.1 §3.1 (fallback 三档)。30-50-100 三档 acceptance:
- ≥ 30 真 query → 跑一遍 sweep,标 "preliminary"
- ≥ 50 → fallback 到 v0.2 + v0.3 mix sweep
- ≥ 100 → v0.3 ready,跑 ADR re-sweep + Ragas

ETA: gated(不在我们控制内,等 real users)。

### 3.3 P0: Streamlit WS F12 复测(KPI 5)

继承自 v2.3 §3.9。User 浏览器 30 min 操作:
- F12 Network 看 `_stcore/stream` Status 101 / 200 / failure
- 对应改 cloudflared `originRequest` 配置 / Streamlit `--server.enableCORS=false`
- SOP 在 [docs/streamlit_ws_troubleshooting.md](streamlit_ws_troubleshooting.md)

**何时做**: 任何时候 user 方便(不阻塞)。

### 3.4 P1: ADR-0015 / 0016 v0.3 重 sweep(KPI 3)

继承自 v2.3 §3.2。等 KPI 2 v0.3 ready 后:
```bash
uv run python eval/sweep_blend_alpha.py --test-set eval/test_set.json --out-json eval/blend_sweep_results_v03.json
uv run python eval/sweep_reject_threshold.py --test-set eval/test_set.json --out-json eval/reject_threshold_sweep_v03.json
```

按 v2.3.1 加严的 acceptance:**paired bootstrap 95% CI** 替代 ad-hoc "α 漂 > 0.1" 阈值(继承自 v2.3.1 §3.2)。

ETA: 等 KPI 2 后 1.5h。

### 3.5 P1: Ragas eval real Gemini judge(KPI 4)

继承自 v2.3 §3.6 + v2.3.1 §3.6 cross-judge bias 控制。等 KPI 2 后:
```bash
uv run python eval/ragas_runner.py --use-real-gemini --out eval/ragas_v03.json
```

**v2.3.1 加严**:除 Gemini-as-judge 外加一项 cross-validate(Claude or 30 条人工 cohen's κ),记 bias 量化数字。

ETA: 等 KPI 2 后 1h。

### 3.6 P2: 后续监控(non-blocking)

继承 v2.3 §3.10:
- p99 latency monitor(等 ≥ 200 真 query)
- 6469 课 enrich 扩展(§3.4 v2.3,需 prof 名,跳过)

---

## 4. Week 10+ provisional / v4.0 prep

延续 v2.3 §4 + roadmap_v3.md:

| 触发条件 | 解锁的 v4.0 项目 |
|---|---|
| ≥ 500 真 query log | learnable blending(per-query α 或 lightGBM) |
| ≥ 30 真 OAuth 用户 | 社交层 (POST /user_courses + GET /course/{id}/classmates) |
| Andy React 前端落地 | Streamlit 降级 debug-only |
| ORT 1.26+ cu13 build | 重启 TensorRT EP 路径 |
| FP8 encoder benchmark 出来 | Blackwell FP8 量化实验 |
| 用户报告 "selection planner" 需求 | Yuang Dai 双版本 selection planner |

---

## 5. Open TODOs (carry from v2.3.1 + Week 9)

| Priority | TODO | Where | Source |
|---|---|---|---|
| P0 | NAS deploy + OpenVINO EP probe | NAS hardware | v3.0 §3.1 |
| P0 | (gated) v0.3 expansion | `eval/test_set.json` | v2.3.1 §3.1 |
| P0 | (gated) Streamlit WS F12 复测 | 浏览器 + cloudflared cfg | v2.3 §3.9 |
| P1 | (gated) ADR re-sweep + bootstrap CI | sweep scripts | v2.3.1 §3.2 |
| P1 | (gated) Ragas + cross-judge | ragas_runner | v2.3.1 §3.6 |
| P2 | (gated) p99 latency monitor | probe script | v2.3 §3.10 |
| Deferred | TRT EP 路径 | ORT 1.26+ cu13 build | Week 9 |
| Deferred | torch.compile 路径 | 永久 skip on Blackwell + FlagEmbedding | Week 9 |
| Deferred | learnable blending / 社交层 / mobile | v4.0 | roadmap_v3 |

---

## 6. Reference

### 6.1 First 30 minutes for a returning agent

```bash
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass

# 验证状态
git log --oneline | head -5                   # 最近 commit (Week 9 perf 应该在)
uv run pytest tests/ -q                        # 期望 ≥ 679 passed
uv run python scripts/probe_inference_latency.py --label sanity --n 10
# 期望 server p50 ~40-50ms

# 读 v3.0(this doc)→ docs/perf_week9_results.md → docs/PLAN_v2.3.md §1 invariants
cat docs/PLAN_v3.0.md
cat docs/perf_week9_results.md
ls docs/adr/00{13..16}*.md

# 起 stack(本地或 NAS,看部署位置)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
# 等 ~6s(ONNX backend) or ~70s(PyTorch)
```

### 6.2 v3.0 deliverable 一览

| Artifact | Path | 状态 |
|---|---|---|
| NAS 部署 runbook | `docs/nas_deploy_runbook.md` | ⬜ 等到货后写 |
| test_set v0.3 | `eval/test_set.json` (version=0.3) | ⬜ gated traffic |
| α v0.3 sweep | `eval/blend_sweep_results_v03.json` | ⬜ gated v0.3 |
| T v0.3 sweep | `eval/reject_threshold_sweep_v03.json` | ⬜ gated v0.3 |
| Ragas v0.3 results | `eval/ragas_v03.json` | ⬜ gated v0.3 |
| ADR-0015 / 0016 supplements | `docs/adr/0015*.md` / `0016*.md` footers | ⬜ gated v0.3 |
| Streamlit WS verify report | `docs/streamlit_ws_verification.md` | ⬜ gated user F12 |

### 6.3 Conventions

继承 v2.2 §6.3 / v2.3 §6.3 全部:
- Pydantic `extra="forbid"`,Repository takes connection,LLM-callable accepts injectable fn
- Commits: `feat(weekN): ...` / `feat(scope): ...` / `docs: ...` / `fix(weekN): ...` / `test: ...`
- ADRs follow `docs/adr/0000-template.md`
- Tests build on conftest fixtures (FixtureEmbedder / FixtureReranker)

---

## 7. Versioning

- **PLAN v1.0**: 原始 8-week 规划
- **PLAN v1.2 (FINAL)**: PDF revision
- **PLAN v1.3**: Week 0 critique-driven
- **PLAN v2.0**: Week 5 checkpoint
- **PLAN v2.1**: Week 6 checkpoint
- **PLAN v2.2**: Week 7 sprint plan + closeout
- **PLAN v2.3**: Week 8 forward
- **PLAN v2.3.1**: Week 8 hardened review
- **PLAN v3.0**: this file. Phase shift to operational + signal-driven.
- **Next**: v4.0 起社交层 + learnable blending(等 ≥ 500 真 query log + ≥ 30 用户)。

---

## 8. Acknowledged limits + intentional tradeoffs

延续 v2.3 §8 / v2.3.1 §8,新增 Week 9 实测发现:

- **CUDA EP 是 user 现阶段最优 backend**(p50 -8.5%,startup -91%)。继续走这个路径,不要再被 "理论上 TRT EP 更快" 误导
- **TRT EP 在 cu13 系统上不可用**,等 ORT 1.26+。这是 NVIDIA + ORT release schedule 不在我们控制内
- **torch.compile 在 Blackwell + FlagEmbedding 上不可用**。永久 skip,在 v3.0 / v4.0 都不要重试
- **NAS 部署是 v3.0 唯一 active engineering 项目**;其他全部 signal-driven
- **真 traffic 不来 v3.0 没 KPI 2-4** — 这是 product validation 问题不是技术问题,工程不为它阻塞

---

## 9. Migration from v2.3.1 → v3.0

如果你是从 v2.3.1 sprint 切过来:

1. **没有破坏性改动**。v2.3.1 ship 的代码 + 文档全部仍然有效,v3.0 只是新增 NAS 部署项 + perf 实测发现 + signal-driven 模式。
2. **测试 floor 升 660 → 679**。Week 9 加了 13 个 ONNX backend test + 5 个 compile_mode test。
3. **新文件**(都已 commit 到 main):
   - `rag/onnx_backend.py`、`scripts/export_models_onnx.py`、`scripts/probe_inference_latency.py`
   - `docs/tensorrt_runbook.md`、`docs/perf_week9_results.md`
4. **新 env flag**(默认全 off,backward-compat):`INFERENCE_BACKEND` / `ONNX_*` / `ENABLE_TORCH_COMPILE`
5. v2.3 / v2.3.1 仍是 sprint history;v3.0 是 active sprint。

---

**End of v3.0**. Open next session with this doc + perf_week9_results.md 作为 starter context。优先级:NAS 部署 → 等 traffic → 信号触发 ADR re-sweep / Ragas。
