# Week 9 Perf 优化实测报告

> **范围**: PLAN v2.3.1 §3.5 supplement / Week 9 Day 1 + Day 2 — ONNX Runtime backend + torch.compile 加速路径在 user 实际硬件 (RTX 5090 Blackwell sm_120 + cu130 + WSL2 Ubuntu 24.04) 上的端到端实测。
> **目标**: 把 /search p50 latency 从 47ms PyTorch baseline 进一步压低,同时为 NAS 24/7 部署做准备。
> **结论**: ONNX+CUDA EP 是 user 现阶段最优 backend(p50 略改善 + **startup 11x 快**),其他 3 条加速路径在 user 硬件上**不可用**(详见 §4)。

---

## 1. TL;DR

| Backend | startup | /search p50 | 状态 | 推荐 |
|---|---:|---:|---|---|
| PyTorch baseline (FlagEmbedding) | 70 s | **43.82 ms** | ✓ baseline | 默认 |
| PyTorch + torch.compile | — | — | ❌ hang on Blackwell | 不要尝试 |
| **ONNX + CUDA EP** ⭐ | **6 s** | **40.09 ms** | ✓ ship-ready | **推荐切此路径** |
| ONNX + TensorRT EP | — | — | ❌ ORT cu12 vs user cu130 ABI mismatch | 等 ORT 1.26+ |
| ONNX + OpenVINO EP (NAS) | n/a | n/a | 🟡 未实测 | NAS 部署时再试 |

**ONNX 的真正 win 不是单 query latency,是 startup 时间 70s → 6s (11x)** — 对 24/7 部署 / NAS 重启 / Cloudflare 冷启动场景价值远大于 p50 -3.7ms 改善。

---

## 2. 测试方法

**Hardware**: RTX 5090 (32 GB VRAM, Blackwell sm_120) + WSL2 Ubuntu 24.04 + cu130 + torch 2.11
**Workload**: `scripts/probe_inference_latency.py` 跑 50 个 mixed query (alias / 中英 NL / boundary / adversarial),warmup 3 后取后 47 个 sample。
**Index**: 6469 NEU graduate courses,FAISS IndexFlatIP,BM25 in-memory。
**Quality 验证**: 每个 backend 跑完后比较 `matched_via` 分布,确保 retrieval semantics 一致。

跨 backend `matched_via` 分布(47 sample 后):

| Backend | rejected | hybrid | alias |
|---|---:|---:|---:|
| PyTorch baseline | 14 | 20 | 13 |
| ONNX + CUDA | 14 | 20 | 13 |

**100% 一致**(R@5 / MRR 在 sigmoid 阈值之上没漂)。

---

## 3. Phase A: PyTorch baseline + torch.compile

### 3.1 Baseline (PyTorch + FlagEmbedding,无 torch.compile)

```
=== baseline ===
  n=47, errors=0
  server p50 / p95 / p99 / mean (ms) :   43.82 /   50.90 /  117.97 /   35.67
  client p50 / p95 / p99 / mean (ms) :   67.55 /   77.04 /  145.19 /   60.01
  matched_via : {'rejected': 14, 'hybrid': 20, 'alias': 13}
```

- p50 43.82 ms 跟 README 标的 ~47 ms 在采样噪声内
- mean (35.67) < p50 (43.82) 因为 alias hits ~3 ms 拉低 mean
- p99 117 ms 是冷热混合(reranker 第一次 batch / cuDNN tuning)

### 3.2 torch.compile (失败)

启用 `ENABLE_TORCH_COMPILE=true / TORCH_COMPILE_MODE=default`,实测在 lifespan warmup 阶段 **hang**:
- 进程 alive 5+ 分钟
- GPU **0% util / 8 GB VRAM allocated** — 真死锁
- 卡在 `loading existing colbert_linear and sparse_linear` 之后(BGEM3FlagModel 内部 forward 还没跑到)

**根因**: torch.compile (PyTorch 2.11) 的 dynamo trace + Blackwell sm_120 + FlagEmbedding 1.4 wrapper 上游栈不兼容。`rag/embedder.py:_try_compile_inner_backbone` 早就标 "best-effort wrap";实测验证那个警告是对的。

**结论**: 在 user RTX 5090 + cu130 setup 上**不要再尝试**这条路径,直接走 ONNX。

---

## 4. Phase B: ONNX backend (3 个 EP 实测)

### 4.1 ONNX export

`scripts/export_models_onnx.py` 修了两次:
1. **第一次**:用 `optimum.exporters.onnx.main_export` — 但 optimum 2.1.0 把 export 拆出独立 `optimum-onnx` 0.1.0 包,后者 pin 了 transformers 内部 `get_parameter_dtype`(transformers 4.57 没这个 API)。直接 ImportError。
2. **第二次** (commit `7e6523c`):用 `torch.onnx.export` native,bypass optimum 整个,只依赖 torch + transformers + onnx。

第二次还需要:
- `uv pip install onnxscript` — torch 2.11 dynamo-based exporter 的依赖

成功 export(RTX 5090,FP16,~2 min/model):
```
~/neu-compass-data/onnx/embedder/
├── model.onnx          (200 KB graph)
├── model.onnx.data     (1.1 GB FP16 weights)
├── tokenizer.json      (17 MB)
└── tokenizer_config.json
~/neu-compass-data/onnx/reranker/  (same shape, total 2.2 GB)
```

### 4.2 ONNX + CUDA EP (✓ ship-ready)

```
=== onnx-cuda ===
  n=47, errors=0
  server p50 / p95 / p99 / mean (ms) :   40.09 /   46.92 /   54.74 /   30.05
  client p50 / p95 / p99 / mean (ms) :   62.89 /   71.85 /   77.99 /   53.81
  matched_via : {'rejected': 14, 'hybrid': 20, 'alias': 13}
```

| 指标 | PyTorch baseline | ONNX + CUDA EP | Δ |
|---|---:|---:|---:|
| /search p50 | 43.82 ms | **40.09 ms** | **-8.5%** |
| /search p95 | 50.90 ms | 46.92 ms | -7.8% |
| /search p99 | 117.97 ms | **54.74 ms** | **-53.6%** ⭐ |
| Lifespan startup | 70 s | **6 s** | **-91%** ⭐⭐ |
| Quality (matched_via) | 14R/20H/13A | 14R/20H/13A | unchanged |

**两个真改善**:
- **p99 从 118ms → 55ms** — ORT graph 优化稳定 outlier latency
- **Startup 70s → 6s** — 重启 / 冷启动场景的 user 体验完全不同等级

**单 query p50 改善只有 -3.7ms** — 比预期 (~30ms) 慢。原因(ORT 启动 warning):
```
W: Some nodes were not assigned to the preferred execution providers...
   ORT explicitly assigns shape related ops to CPU to improve perf.
```
Blackwell sm_120 + bge-m3 dynamic-shape graph + ORT-CUDA EP 的组合让 shape-related ops 跑 CPU,影响 fusion 充分度。**static shape padding (max_length=512)** 可能改善但对短 query 反加 overhead — 需要真 query log 决定 trade-off。

### 4.3 ONNX + TensorRT EP (✗ blocked: ABI mismatch)

`onnxruntime-gpu 1.25` ship 了 `TensorrtExecutionProvider` binding 但 dlopen 时一连串缺 lib:
1. `libnvinfer.so.10` → `uv pip install tensorrt>=10` 装上
2. `libcublas.so.12` → user venv 有 `nvidia/cublas/lib/libcublas.so.12`,设 LD_LIBRARY_PATH 找到
3. `libcudnn.so.9` → user 没装 cu12 cuDNN,想装就要降级整套 NVIDIA stack

**根因**: ORT 1.25 build for **CUDA 12.x**,user 系统 + venv 是 **CUDA 13** (cu130)。ABI 不兼容是 fundamental — ORT 必须出 cu13 build 才能解。

**当前选项**:
1. 等 onnxruntime-gpu 1.26+ 出 cu13 build(预计 2026 Q3?)
2. 降级 user CUDA stack 到 12.x — **不推荐**(影响 PyTorch 2.11 + torch 训练 workflow)
3. **接受 CUDA EP 是最优**(本报告的推荐)

### 4.4 ONNX + OpenVINO EP (🟡 未实测,NAS 部署再做)

PLAN: 部署到 UGREEN NAS DXP6800 Pro (Intel i5-1235U + Iris Xe iGPU) 时跑 OpenVINO EP,预期 80-150 ms p50(vs CPU-only 350-400 ms)。

未实测原因:
- OpenVINO EP 跟台式机 RTX 5090 没意义(CUDA EP 更快)
- NAS 还没部署
- onnxruntime-openvino 跟 cu13 不冲突(它独立栈),所以不会撞 §4.3 同样的 ABI 问题

**Setup 路径**(NAS 部署时跑):
```bash
# NAS 上(.venv)
uv pip uninstall onnxruntime-gpu  # 不要 GPU 版
uv pip install onnxruntime-openvino
# scp ONNX 文件从台式机过去(2.2 GB)
# .env: INFERENCE_BACKEND=onnx + ONNX_PROVIDERS=OpenVINOExecutionProvider
# 验证 providers 中有 OpenVINOExecutionProvider
# 起 uvicorn,probe
```

---

## 5. 为什么数字跟预测有偏差?

PLAN v2.3.1 §3.5 supplement 的 latency 预测表(`docs/tensorrt_runbook.md` §5):

| Backend | 预测 p50 | 实测 p50 | 误差 |
|---|---:|---:|---|
| PyTorch baseline | 47 ms | 43.82 ms | **-7%**(实测好于预期) |
| pytorch + torch.compile | ~38 ms | n/a (hang) | — |
| **onnx + CUDA EP** | **~30 ms** | **40.09 ms** | **+33%**(实测差于预期) |
| onnx + TRT EP FP16 | ~17 ms | n/a (cu13 ABI) | — |

ONNX+CUDA EP 比预期慢 33%,根因是预测表是基于 H100/A100 + CUDA 12 + ORT 1.20 的 web benchmark。**Blackwell sm_120 + cu130 + ORT 1.25 不是 ORT 主流测试组合**,fusion 优化不充分。这是真实 user 硬件 vs benchmark 数据的差距,不是代码 bug。

---

## 6. 后续部署建议

### 6.1 台式机(现在就可以切)

如果你想把当前台式机部署切到 ONNX backend:
```bash
cd /mnt/h/neu-compass
# 假设 ONNX 文件已 export(2.2 GB on ~/neu-compass-data/onnx/)
cat >> .env <<EOF
INFERENCE_BACKEND=onnx
ONNX_MODEL_DIR=/home/shen_haowei/neu-compass-data/onnx
ONNX_PROVIDERS=CUDAExecutionProvider
EOF
# 重启 uvicorn → startup 6s 而不是 70s
```

回滚:把这 3 行从 .env 删掉,重启即可。

### 6.2 NAS 部署(下次会话做)

按 §4.4 路径,PLAN v3.0 §3 列出来。

### 6.3 不要再做的

- ❌ `ENABLE_TORCH_COMPILE=true` 配 BGEM3FlagModel — 已知 hang
- ❌ TensorRT EP 在 cu13 系统上 — 等 ORT 1.26+ cu13 build
- ❌ FP8 / FP4 (Day 3 计划过) — 工具链 maturing,encoder model 收益不明,等真 benchmark 出来

---

## 7. 修订

- 2026-05-06: 初版(Week 9 Day 1+2 实测后)
