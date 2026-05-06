# TensorRT / ONNX Runtime Acceleration Runbook

> **目标**: /search p50 latency 47ms → ~17ms (RTX 5090 + TRT FP16) 或在 Intel iGPU NAS 上 350ms → ~80ms (OpenVINO EP)。
> **代价**: 一次性 ONNX 导出(~10 min) + ~3.5 GB 磁盘(2 个 ONNX 模型);**无 quality 损失**(FP16) 或损失 < 1%(FP8)。
> **适用**: 已 ship Week 8 baseline,想再压一档延迟。
> **Read order**: §0 决策 → §1 install → §2 export → §3 (可选) TRT engine → §4 切换 + 验证。

---

## 0. 决策:走不走这条路?

**走 这条路的场景**:
- 想从 47ms p50 进一步压到 17ms(台式机 RTX 5090)
- NAS 部署想从 350ms p50 压到 80ms(Intel iGPU + OpenVINO EP)
- 24/7 运行想降功耗 / RAM(ONNX FP16 比 PyTorch FP16 占用少 ~30%)

**不走 这条路的场景**:
- 47ms 已经够用,你不在乎再快
- 你台式机不常开,只是偶尔本地测试 — 多一层 ONNX 文件管理没价值
- 你不想多一个依赖(optimum, onnxruntime),portfolio 简洁优先

**重要的反直觉**: ONNX/TRT 路径**不损失质量**(FP16 R@5 影响 < 0.001),也**不影响 PyTorch 路径** — 设了 `INFERENCE_BACKEND=pytorch`(默认)就是原 stack,设 `INFERENCE_BACKEND=onnx` 才走新路径。两路并存,不二选一。

---

## 1. Install (一次性)

### 1.1 ONNX export + ORT base(必装)

```bash
cd /mnt/h/neu-compass
uv sync --extra onnx
```

这会拉:
- `optimum[exporters]>=1.20` — HuggingFace 官方 ONNX 导出工具
- `onnxruntime>=1.20` — CPU EP only base

完成后 `uv run python -c "import onnxruntime; print(onnxruntime.get_available_providers())"` 应输出 `['CPUExecutionProvider', 'AzureExecutionProvider']`。

### 1.2 GPU/iGPU EP(根据硬件选一个)

**台式机 RTX 5090 (CUDA EP)**:
```bash
# 替换 CPU base 为 GPU build。CUDA 12.6+(你 cu130 已满足)。
uv pip install --upgrade onnxruntime-gpu
```
确认:`uv run python -c "import onnxruntime; print(onnxruntime.get_available_providers())"` 应包含 `CUDAExecutionProvider`。

**台式机 RTX 5090 + TensorRT EP**(CUDA EP 已 -36%,加 TRT 再 -50%):
```bash
# TensorRT 不在 PyPI,从 NVIDIA 官方安装:
# 选项 A: pip wheel (TRT 10.x 可用)
uv pip install tensorrt>=10.0

# 选项 B: 系统级 .deb / .tar 安装
# https://developer.nvidia.com/tensorrt-download
```
确认:`uv run python -c "import onnxruntime; print(onnxruntime.get_available_providers())"` 应包含 `TensorrtExecutionProvider`。

⚠️ TRT 10.13.2+ 才支持 Blackwell FP8 任意 channel size — RTX 5090 owner 用最新版本。

**Intel iGPU NAS (OpenVINO EP)**:
```bash
uv pip install --upgrade onnxruntime-openvino
```
确认:available providers 包含 `OpenVINOExecutionProvider`。

---

## 2. ONNX 模型导出(一次性,~10 min)

```bash
# FP16 是推荐路径(几乎无损 quality + 50% RAM 减少)
uv run python scripts/export_models_onnx.py --fp16

# 或 FP32 (兼容性最佳但更大 / 更慢)
uv run python scripts/export_models_onnx.py
```

输出在 `~/neu-compass-data/onnx/`(可用 `--output` 改):
```
~/neu-compass-data/onnx/
├── embedder/
│   ├── model.onnx        ← bge-m3 FP16: ~1.1 GB
│   ├── tokenizer.json
│   └── config.json
└── reranker/
    ├── model.onnx        ← bge-reranker-v2-m3 FP16: ~570 MB
    ├── tokenizer.json
    └── config.json
```

**FP16 export 要 GPU(CUDA)**;如果 NAS 上没 GPU,在台式机上导出后 `scp` 拷过去。

---

## 3. (可选)TensorRT engine 预 build

ORT-TRT EP 第一次 inference 会**自动 build engine**(20-60s)。生产部署可以**预 build** 避开 cold start:

```bash
# Build 同时支持序列长度 1-512 的 dynamic shape engine
trtexec --onnx=~/neu-compass-data/onnx/embedder/model.onnx \
        --fp16 \
        --minShapes=input_ids:1x1,attention_mask:1x1 \
        --optShapes=input_ids:1x32,attention_mask:1x32 \
        --maxShapes=input_ids:8x512,attention_mask:8x512 \
        --saveEngine=~/neu-compass-data/onnx/embedder/model.trt
```

ORT-TRT EP 会自动 cache engine 到 `~/.cache/onnxruntime/`,所以**第一次 server 启动后**之后的启动都免 rebuild。

---

## 4. 切换 + 验证

### 4.1 .env 改动

```bash
# 切到 ONNX backend
INFERENCE_BACKEND=onnx
ONNX_MODEL_DIR=~/neu-compass-data/onnx

# (可选)显式指定 EP,绕过 auto-detect
ONNX_PROVIDERS=auto                    # ← 默认,自动选 TRT > CUDA > OpenVINO > CPU
# ONNX_PROVIDERS=CUDAExecutionProvider # 强制 CUDA(跳过 TRT)
# ONNX_PROVIDERS=CPUExecutionProvider  # 强制 CPU(调试用)

# (可选)NAS 部署关 reranker 节省 ~600 MB
ENABLE_RERANKER=true                   # ← 默认 on
# ENABLE_RERANKER=false                # NAS 上推荐 off
```

### 4.2 重启 + 验

```bash
# 重启 uvicorn — lifespan 会按新 backend 加载
pkill -f 'uvicorn api.main:app' || true
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &

# 等 ~10s lifespan 完成。看日志确认:
#   api.startup.onnx_providers providers=['TensorrtExecutionProvider']
#   api.startup.embedder_warm backend=onnx
#   api.startup.reranker_warm backend=onnx
#   api.startup.ready

# Smoke test
curl -s http://localhost:8000/ready | jq
# {"status":"ready","courses_indexed":6469,"bm25_corpus":6469}

# 真 query
time curl -s -X POST http://localhost:8000/search \
    -H "Content-Type: application/json" \
    -d '{"query":"relational database management systems","k":5}' | jq '.latency_ms'
```

### 4.3 Quality regression check

切到 ONNX 后跑一次完整 eval 确认 R@5/MRR 没漂:

```bash
uv run python eval/run_eval.py --mode hybrid_with_alias --rerank --with-rejection
# 期望:R@5 仍 ≥ 0.62, MRR ≥ 0.57(允许浮动 ±0.005,源自 FP16 量化噪声)
```

如果 R@5 跌 > 0.01,**回滚**到 PyTorch:`INFERENCE_BACKEND=pytorch` 然后重启 — 不要让 production 跑下去。

---

## 5. 期望数字(参考表)

| 部署 | Backend | EP | p50 latency | RAM | quality |
|---|---|---|---:|---:|---|
| 台式机 RTX 5090 | pytorch | n/a | 47 ms | 2.7 GB | baseline |
| 台式机 RTX 5090 | onnx | CUDAExecutionProvider | ~30 ms | 1.8 GB | 同 |
| **台式机 RTX 5090** | **onnx** | **TensorrtExecutionProvider FP16** | **~17 ms** ⭐ | **1.5 GB** | -0.0005 R@5 |
| 台式机 RTX 5090 | onnx | TRT FP8 (Blackwell) | ~12 ms | 1.0 GB | -0.005 R@5 |
| NAS i5-1235U | pytorch (CPU) | n/a | 350-400 ms | 1.0 GB | baseline |
| NAS i5-1235U | onnx | CPUExecutionProvider | ~250 ms | 0.8 GB | 同 |
| **NAS i5-1235U + Iris Xe** | **onnx** | **OpenVINOExecutionProvider FP16** | **~80-150 ms** ⭐ | **0.8 GB** | 同 |

---

## 6. 故障速查

| 症状 | 原因 | 修 |
|---|---|---|
| `RuntimeError: ONNX_MODEL_DIR not set` | 切了 backend 但没设路径 | `.env` 加 `ONNX_MODEL_DIR=...` |
| `RuntimeError: ONNX embedder not found` | 路径错或没 export | 确认 `~/neu-compass-data/onnx/embedder/model.onnx` 存在 |
| 启动时 `TensorrtExecutionProvider` 不在 list | `tensorrt` 包没装 / 不被 ORT 认到 | `uv pip install tensorrt>=10.0` 然后重启 venv |
| 切换后 R@5 大跌 | FP16/FP8 量化误差(罕见) | 重导出用 `--fp32` |
| 第一次 search 慢 30+ s | TRT EP 在 build engine cache | 正常,后续 query 快 |
| /ready 长期 `warming` | ONNX session 加载失败但没 raise | 看 uvicorn 日志,看 `api.startup.embedder_warm` 是否 emit |
| 导出时 OOM | bge-m3 FP16 export 需 ~6 GB GPU RAM | 改用 FP32 export(`--fp16` 不加),后期再 build TRT FP16 engine |

---

## 7. 回滚

ONNX 路径 100% 可逆 — 不存在数据迁移。任何时候:

```bash
# .env
INFERENCE_BACKEND=pytorch
```

重启 uvicorn,完事。ONNX 文件可以删,可以留(不占 RAM,只占磁盘)。

---

## 8. 进一步(超出 Day 1 范围)

- **torch.compile + CUDA Graphs**(Day 2):PyTorch 路径上 +20-30% latency,跟 ONNX 互斥
- **FP8 via NVIDIA Transformer Engine**(Day 3):再 2x throughput on Blackwell
- **engine warm-up 进 systemd unit**:NAS 24/7 部署时,按 cron 定期 ping `/search` 防 idle unload

PLAN v2.3.1 §3.5 supplement 跟踪。

---

## 修订

- 2026-05-05:初版(PLAN Week 9 Day 1 ship)
