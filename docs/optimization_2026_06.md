# 2026-06 全面优化 — code review + 文献/仓库调研 + 落地

> 输入：全库 deep review(24k LOC / 147 py 文件)+ 30 篇 paper 调研 + 35 个参考仓库调研。
> 本批落地 12 项(全部测试覆盖,739 → **762 passed / ~14s**)。未动 API contract 与 NAS 部署形态。

## 一、本批已落地(代码可 diff)

### 正确性
| # | 修复 | 文件 | 影响 |
|---|---|---|---|
| 1 | **give-to-get 断链**:POST /coop 从不调用 `increment_contribution_count`,贡献者永远解锁不了 tier 1/2 | [api/routes/coop.py](../api/routes/coop.py) | 产品核心回路恢复;同事务提交 |
| 2 | **BM25 零分填充**:argsort 恒返回 k 条,与 query 零词重叠的 doc 也挤进 RRF 分 mass | [rag/hybrid.py](../rag/hybrid.py) `BM25Corpus.search` | 用 per-doc token set 过滤(IDF 退化时真命中仍保留);eval 数字逼近锁定阈值,这是免费的 R@5 修正 |
| 3 | **BM25 leg 被向量 top-k 截断**:hard filter 下 BM25 只能从向量 top-(k*3) 交集里选,过滤通过但向量排 #61 的课被静默丢弃 | [rag/hybrid.py](../rag/hybrid.py) + [rag/retriever.py](../rag/retriever.py) `filter_ids` | BM25 leg 现在 scope 到与向量 leg 相同的 SQLite 过滤集 |
| 4 | **INFO/IE 前缀误判**:`"any info on ML courses"` 被解析成 `primary_code LIKE 'INFO %'` 硬过滤 | [llm/query_filter_extractor.py](../llm/query_filter_extractor.py) `AMBIGUOUS_PREFIXES` | 歧义前缀只接受全大写拼写 |
| 5 | **eval 默认值漂移**:`run_eval.py --reject-threshold` 默认 0.4,生产是 0.05(ADR-0016) | [eval/run_eval.py](../eval/run_eval.py) | 复现 eval 不再测错 operating point |

### 性能
| # | 优化 | 文件 | 实测/预期 |
|---|---|---|---|
| 6 | **事件循环阻塞**(review 评定 #1 结构性问题):所有重路由是 `async def`,embedder+reranker 前向(NAS 上秒级)直接跑在 event loop 上,饿死 /health /ready → Docker healthcheck 连环重启风险 | [api/routes/search.py](../api/routes/search.py) / [chat.py](../api/routes/chat.py) / [auth.py](../api/routes/auth.py) / [coop.py](../api/routes/coop.py) 全部转 sync `def`(FastAPI threadpool) | 并发下 API 保持响应;NAS 上是"1 个可用并发"到"N 个"的差别 |
| 7 | **模型单例线程锁**:转 threadpool 后并发请求会同时打模型;optimum-intel `OVModel*` 单 InferRequest **非线程安全** | [rag/embedder.py](../rag/embedder.py) / [reranker.py](../rag/reranker.py) / [onnx_backend.py](../rag/onnx_backend.py) / [openvino_backend.py](../rag/openvino_backend.py) 各加 `threading.Lock` | 6 的前置条件 |
| 8 | **向量 leg N+1**:每次 /search 60 个单行 SELECT + 60 次 Course Pydantic 解析(k*3 候选 × 逐条 `repo.get`) | [rag/retriever.py](../rag/retriever.py) `search_ids` + `get_batch` hydration;HybridRetriever 走 ID-only 路径 | -60 SELECT/-60 parse 每请求 |
| 9 | **reranker 取文 N+1**:`_fetch_text` 闭包 ≤20 单行 SELECT,且 search/chat 双份重复 | [api/routes/common.py](../api/routes/common.py) `fetch_texts`(单条 IN 查询)+ `build_hard_filters` 去重 | 1 次 round-trip;-80 LOC 重复 |
| 10 | **α sweep 9 倍冗余**:`sweep_blend_alpha` 每个 α 重跑 reranker(sigmoid 与 α 无关);`sweep_reject_threshold` 早就是一遍式设计 | [eval/sweep_blend_alpha.py](../eval/sweep_blend_alpha.py) score-once-reblend | 9-α sweep 模型时间 ≈ 1/9;v0.3 test set 重扫前必备 |

### 韧性
| # | 修复 | 文件 |
|---|---|---|
| 11 | SQLite `busy_timeout=5000` + `synchronous=NORMAL`(WAL 标配);Gemini client 120s 硬超时(原来挂死即永久占位);JWKS kid-miss 时 cache_clear + 单次重试(原来 Google 轮换密钥后全员登录失败直到重启);ApiClient 10s→30s + Timeout→ApiError(原来 NAS 冷路径直接甩 Streamlit traceback) | [db/connection.py](../db/connection.py) / [llm/gemini_client.py](../llm/gemini_client.py) / [app/auth.py](../app/auth.py) / [app/api_client.py](../app/api_client.py) |
| 12 | **OpenVINO backend 测试从 0 → 14 个**(生产真正在跑的 backend 原本是唯一零覆盖的);构造注入 fake 不需要 optimum-intel/torch | [tests/test_openvino_backend.py](../tests/test_openvino_backend.py) |

## 二、Review 发现但本批**刻意不动**的(需要决策/部署验证)

1. **`X-User-Id` header 完全被信任**(#1 安全项):LAN 上任何人可读 level-2 薪资数据。OAuth+JWT 链路对 API 鉴权是装饰性的。修法:`/auth/callback` 签发 itsdangerous session token(依赖已在 pyproject 里且未使用)+ OAuth `state` CSRF + compose 里 8000 端口改 loopback。**改 API contract,等 Andy 前端对齐一起做。**
2. **NAS 镜像瘦身 8-10GB → 2-3GB**:运行时镜像装了 FlagEmbedding(→CUDA torch)/playwright/ragas/deepeval/praw。前置条件:`OvEmbedder` 的 `return_tensors="pt"` 改 `"np"` 以切断 torch 依赖——需在 NAS 上实际验证 optimum-intel 对 np 输入的返回类型,本批没盲改。
3. **UI 容器拿到整个 .env**(Gemini key 等),且 `settings.py` 把 scraper 凭证设为 required 导致 UI 不能没有它们——配置解耦待做。
4. k-anonymity gate 仍是 `list_all()` O(n·parse)(30 行无所谓,500 行该换 `SELECT COUNT`);两个并发首传同 triple 能双双过门(竞态)。
5. HyDE 是完整实现+测试但生产零调用的死代码——要么挂 flag 要么标 experimental。

## 三、文献调研 → 行动清单(按预期收益排序)

NAS p50 2.3s 的瓶颈 100% 在 reranker(20 pair × seq 512 cross-encoder)。flat FAISS @ 6.5k 向量已是 exact + 亚毫秒,**HNSW/IVF/embedding 量化/MRL 都不要做**([HF 量化分析](https://huggingface.co/blog/embedding-quantization))。

1. **Rerank pool 20→10**:[Drowning in Documents (SIGIR'25)](https://arxiv.org/abs/2411.11767) — cross-encoder 质量不随 pool 单调升,top-10 大概率白拿 ~2x 延迟减半。eval 一跑即验。
2. **Reranker seq 512→256 + OpenVINO int8**:课程描述短;`scripts/export_openvino.py --weight-format int8` 钩子已存在没人用。预期再 1.5-2x。
3. **late-interaction 替换 cross-encoder**:[answerai-colbert-small-v1](https://huggingface.co/answerdotai/answerai-colbert-small-v1)(33M)文档侧离线预计算,查询时只算 MaxSim — 2.3s → 低百 ms 量级的架构性解法。注意英文为主,需在中英混合 query 上先验证(多语可用 jina-colbert-v2)。bge-m3 本身就输出 ColBERT 向量(目前被丢弃)。
4. **RRF(k=60) → tuned convex combination**:[Bruch et al., TOIS'23](https://arxiv.org/abs/2210.11934) — z-norm 后凸组合稳定优于 RRF,且项目已有 z-score 管线,等于把 ADR-0015 的机制往上游再推一层。
5. **rank_bm25 → BM25S**:[arXiv:2407.03618](https://arxiv.org/abs/2407.03618) — eager sparse scoring,100-500x,半小时工作量。
6. **eval set n=42 是当前一切调参的天花板**:[Urbano SIGIR'19](https://arxiv.org/pdf/1905.11096) 量级上 n=42 只能可靠分辨 ≥0.10-0.15 的 R@5 差——ADR-0015/0016 锁的差异都在噪声区。用 [UMBRELA](https://arxiv.org/pdf/2406.06519)(Gemini 标注真实 query log)+ [ARES PPI](https://arxiv.org/abs/2311.09476) 扩到 200+。**这条是 1-5 的前置。**
7. **拒绝阈值校准**:[Explain then Rank (ACL'25)](https://arxiv.org/abs/2402.12276) — raw sigmoid 标尺不稳,换 reranker 就漂;用 [UAEval4RAG](https://arxiv.org/abs/2412.12300) 合成不可答 query + Platt/isotonic 校准替代裸 0.05。
8. **program ontology 路线被论文背书**:[Aurora (ACM SAC'26)](https://arxiv.org/pdf/2602.17999) 同构系统(课程 DB + 符号引擎 + LLM 只做解释)对齐度 0.68→0.93;该把更多问题类型(degree audit / 学分计数 / 先修链)路由到 SQLite 符号路径而非检索。先修图多跳可参考 [Edu-GraphRAG](https://arxiv.org/html/2506.22303v1)。
9. **HyDE 复活的正确姿势**:[From Interests to Insights](https://arxiv.org/abs/2412.19312)(课程推荐同域)— 对模糊兴趣 query 用 LLM 生成"理想课程描述"再 embed,恰好接住现有 hyde.py 死代码。

## 四、仓库调研 → 先读这几个

| 仓库 | 看什么 |
|---|---|
| [michaelfeil/infinity](https://github.com/michaelfeil/infinity) | `inference/batch_handler.py` — 动态 batching 队列,从"handler 里直接调 ONNX"到真 serving 层的缺失件 |
| [huggingface/optimum-intel](https://github.com/huggingface/optimum-intel) | `notebooks/openvino/sentence_transformer_quantization.ipynb` — NNCF int8 量化菜谱,几乎逐行适用于 bge-m3/reranker + Iris Xe |
| [lancedb/lancedb](https://github.com/lancedb/lancedb) | Python `rerankers/` 包 — RRF/LinearCombination/CrossEncoder/Colbert 全部 policy-object 化,是 fusion 策略可插拔的最干净表达 |
| [asg017/sqlite-vec](https://github.com/asg017/sqlite-vec) + [作者 hybrid search 博文](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html) | FTS5+vec 的 RRF SQL CTE — 评估把 FAISS+rank_bm25 整层塌缩进 SQLite(NAS 哲学:更少活动件) |
| [deepset-ai/haystack](https://github.com/deepset-ai/haystack) | `components/joiners|routers|rankers/` — 三个 pipeline 阶段各 ~200 行的生产级参照 |
| [run-llama/llama_index](https://github.com/run-llama/llama_index) | `router_query_engine.py` + `SQLAutoVectorQueryEngine` — 先修/培养方案 query 路由到 SQL 的成熟 pattern |
| [AnswerDotAI/rerankers](https://github.com/AnswerDotAI/rerankers) | 统一 API 零胶水 A/B bge vs mxbai vs LLM reranker |
| [beir-cellar/beir](https://github.com/beir-cellar/beir) | 自有 corpus 的 nDCG/R@k 标准化 eval,把检索层和生成层的度量分开 |

域内结论:开源世界没有"catalog RAG + hybrid 检索 + 先修图"三件套都做好的项目;本项目在该 niche 已处于公开 frontier。
