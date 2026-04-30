# RAG Pipeline 端到端 Smoke 测试 (Week 4)

> 跑日期: 2026-04-30
> 环境: WSL2 Ubuntu 24.04 / Windows 11 host / RTX 5090 / CUDA 13.2
> torch 2.10.0+cu128 / FlagEmbedding 1.2 / faiss-cpu 1.13

## 1. 环境验证

```
GPU: NVIDIA GeForce RTX 5090
VRAM: 32.4 GB free / 34.2 GB total (空载)
torch.cuda.is_available(): True
```

## 2. bge-m3 首次下载 + 加载

| 阶段 | 耗时 | 说明 |
|---|---|---|
| 首次下载 + load + encode 1 doc | **99.7s** | 含 ~2GB 模型从 HF Hub 下载 |
| 第二次（缓存命中）load + encode 1 doc | **71.9s** | 模型已在 `~/.cache/huggingface/`,但 Python 进程重启每次都重 load |
| Steady state: 4 docs batch (model 已驻 GPU) | **0.150s** = 27 docs/sec | 这是真实持续吞吐 |

**含义**: 在 FastAPI / Streamlit 的长寿进程里,模型只 load 一次（启动时 ~70s）。
之后 query latency 是 batch 推理时间。**API 冷启动需要 70s warm-up,生产部署时
要么预热,要么用 `uvicorn --workers=1` 避免来回 fork。**

## 3. 跨课向量相似度（基线 sanity）

只有 4 个虚构 syllabus stub 文本（不是真 raw_text）:

| | CS 5800 | DS 5220 | MATH 7243 |
|---|---|---|---|
| AAI 6600 (AI) | 0.528 | 0.593 | 0.555 |
| CS 5800 (algos) | — | 0.588 | 0.541 |
| DS 5220 (ML) | — | — | **0.663** |

最相似对是 DS 5220 (ML) ↔ MATH 7243 (math) = 0.663。这符合直觉
（ML 重数学）。**所有跨课相似度都在 0.5-0.7 区间挤着** —— bge-m3
对相关 STEM 文本的天然分辨率有限,这是 Week 5 上 BM25 hybrid + reranker
的动机。

## 4. End-to-end RAG: AAI 6600 真 raw_text

`scripts/rebuild_faiss.py` 跑了一次，从 SQLite 真相源生成 FAISS 索引:

```
=> rebuilding FAISS index
   db:    /home/shen_haowei/neu-compass-data/courses.db
   index: /home/shen_haowei/neu-compass-data/faiss_index
   filter: status=indexed
=> embedded     : 1
   skipped (no raw_text): 0

real    1m17.923s
```

输出文件:
```
~/neu-compass-data/faiss_index/
├── index.faiss   4194 bytes  (1 个 1024-dim float32 向量 + IndexIDMap 元数据)
└── id_map.json     80 bytes  (course_id <-> int64 映射)
```

77秒里 73秒是 bge-m3 模型加载。单条 embed 实际 < 1秒。**100 课规模
的全量 rebuild 估计 ~80秒**（load + 100 doc batch encode），这是 ADR-0013
兜底脚本的实际成本。

## 5. End-to-end retriever 真实查询

模型已驻 GPU 后，真实 user-style queries 的端到端延迟:

| Query | Latency | Score | 评价 |
|---|---:|---:|---|
| "I want to learn AI fundamentals from scratch" | 29ms | **0.616** | 最高 ✓ |
| "course covering Bayesian methods and search algorithms" | 18ms | 0.568 | syllabus 主题命中 ✓ |
| "machine learning practical project" | 22ms | 0.520 | CLO3 项目要求 ✓ |
| "hybrid course Tuesday evening" | 14ms | 0.484 | 格式信息命中 |
| "quantum mechanics graduate seminar" | 15ms | **0.412** | 最低 ✓（应该miss） |

**Latency**: 14-29ms 端到端。PLAN p50 < 1.5s 目标有 50x headroom。
**排名**: 相对正确。强相关 (0.616) > 弱相关 (0.412)。差值 0.204。

## 6. 局限 + 下一步

### 已知局限

1. **只有 1 个课在索引里** — 任何 query 都会返回 AAI 6600（没别的可选）。
   真正的 ranking 质量需要 ≥10 课才能测，最好 ≥50 课。
2. **score 分布压缩** — bge-m3 在相关 STEM 文本上自然只有 0.4-0.7 区间，
   绝对阈值 (e.g. score < 0.5 = no match) 不可靠。需要 hybrid + 相对阈值。
3. **无 reranker** — Top-K 之后没有 cross-encoder 精排，第 1 名和第 5 名
   差异可能很小。Week 5 v2 路线图里。

### 实测下来值得记录的工程教训

1. **Cold start 70秒不可忽略** — FastAPI / Streamlit 启动期间不要接流量。
   docker-compose 的 `healthcheck` 应该等到 `/health` 返回（含 model loaded）。
2. **rebuild_faiss 单次成本** — 80秒级，不能放在 hot path。每天 cron 一次足够，
   不要在用户请求里调用。
3. **WSL home / 5090 / cu128 配合 OK** — torch 2.10 + CUDA 12.8 + FlagEmbedding 1.2
   开箱即用，没有玄学报错。ADR-0006 (WSL2 强制) 决策被实战验证。

### 下一步具体动作

- [ ] **Week 5 主线**: HyDE Query Expansion / BM25 hybrid / Ragas / 学生黑话词典
- [ ] **数据维度**: 让团队把另外 19 门 Ground Truth 课的 raw_text 收齐
      (从 syllabus.py 跑出来)，丢进 SQLite，然后 rebuild_faiss。这样真排名才有意义
- [ ] **API 预热**: FastAPI startup hook 预先 `embedder.encode([\"warmup\"])`
- [ ] **Score 阈值**: 等多课后跑一组 negative queries (~20 个学生不会问的话题),
      看分布,找 noise floor

## 7. 复现指令

任何时间想再跑这套 smoke:

```bash
# 进 WSL, 启 venv
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
source ~/.bashrc

# 1. 确保 DB 和 status (seed 默认 status=pending,需要手动 mark_indexed)
uv run python scripts/seed_aai6600.py
uv run python -c "
from db.connection import connect
from db.repository import CourseRepository
conn = connect('/home/shen_haowei/neu-compass-data/courses.db')
repo = CourseRepository(conn)
if repo.get_status('neu-aai-6600') == 'pending':
    repo.mark_indexed('neu-aai-6600')
    conn.commit()
conn.close()
"

# 2. rebuild FAISS (~80秒)
uv run python scripts/rebuild_faiss.py

# 3. 查询(自定义脚本，见 docs/rag_smoke_results.md §5)
```
