# NEU-Compass · 8 周执行规划 v1.3

> **版本**: v1.3 · **更新**: 2026-04-30 · **基于**: v1.2 (FINAL) + Week 0 critique
> **下次评审**: Week 2 末

## v1.3 关键变更（相对 v1.2）

| 维度 | 变更内容 | 原因 |
|---|---|---|
| Week 1 范围 | rclone + backup.sh 移到 Week 2 | Day 1 任务密度爆表，挤掉骨架质量 |
| 标注节奏 | Day 6-8 标 8 门 / Day 9 Kappa / Day 10-13 标 12 门 | 给 Cohen's Kappa 争议留修订时间 |
| Week 4 验收 | 加悲观分支：Recall@5 < 0.5 时 Week 5 优先 chunk 策略 | HyDE/BM25 不一定能救场 |
| Seed Data | Week 4 启动 / Week 6 完成 30 条 | 多留 1 周缓冲 |
| UGC 指标 | 拆为「核心贡献者 ≥ 5 人 + 自然贡献率 ≥ 5%」 | 20% 不切实际 |
| PII 脱敏 | 加 k-anonymity 检查（30 条内三元组不允许唯一） | 组合识别风险 |
| 一致性 | 新增「SQLite 是真相源」原则 + rebuild_faiss.py 脚本 | FAISS / SQLite 脱节兜底 |
| Prompt 管理 | 新增 eval/compare_prompts.py（Week 3） | A/B 通道避免改一字降 10 分 |
| Day 3 调整 | Day 1 晚团队人手下载自己的 syllabus | dry run 时序冲突 |

---

## 0. 项目战略定位（v1.2 不变）

### 0.1 定位三句话
1. **不做社交，做 Lead Gen**: 拒绝 DAU/MAU KPI，用工具属性变现
2. **课程 + 求职双引擎**: Course RAG 做流量入口，Co-op 数据做留存飞轮
3. **法律合规优先**: 所有数据源走公开 / API / UGC 路径，不碰受保护数据

### 0.2 不做什么
- ❌ 不做即时聊天（交给微信）
- ❌ 不做 App，先 Web (Streamlit → Next.js)
- ❌ 不做用户画像 / 推荐算法（数据不够）
- ❌ 不做支付系统（F1 合规红线）
- ❌ 不爬 NUworks / Trace / RMP HTML

### 0.3 成功标准（Week 8 末）

| 维度 | 指标 | 目标 |
|---|---|---|
| 数据 | 结构化课程数 | ≥ 20 (Ground Truth) + ≥ 100 (自动) |
| 数据 | Co-op Seed Data | ≥ 30 条高质量面经 |
| 技术 | RAG Recall@5 | ≥ 0.75 |
| 技术 | Faithfulness | ≥ 0.85 |
| 技术 | Context Precision | ≥ 0.80 |
| 用户 | 灰度内测用户 | ≥ 30 NEU 同学 |
| 用户 | 真实 Query 收集 | ≥ 200 条 |
| 用户 | UGC 核心贡献者 | ≥ 5 人 |
| 用户 | 自然 UGC 贡献率 | ≥ 5% |
| 用户 | Latency p50 | < 1.5s（端到端检索） |

---

## 1. 技术架构（v1.2 不变）

技术栈最终决策见 v1.2 §1.1。架构图与 SQLite + FAISS 双层存储设计见 v1.2 §1.2-1.3。
课程别名系统见 v1.2 §1.4（含 v_course_lookup 视图、L1/L2/L3 三层来源）。

**新增红线**：
- **SQLite 是真相源**：写入流程 `SQLite (status='pending') → embed → FAISS → SQLite (status='indexed')`，断点可重建
- **rebuild_faiss.py**：从 SQLite 全量重建 FAISS，作为故障兜底（Week 4 产出）

---

## 2. Schema v1（v1.2 不变）

双层 Pydantic schema 设计见 v1.2 §2。`evidence_snippets` 强制每个软字段附带，`schema_version` 管理迁移。

---

## 3. Ground Truth 课程（20 门）

分布与候选清单同 v1.2 §3。

### 3.3 标注流程（v1.3 修订）

```
Day 1-2:   Schema v1 Pydantic 定义 + 标注指南文档
Day 3:     AAI 6600 dry run（用 Day 1 晚团队预下载的 syllabus）
Day 4-5:   根据 dry run 修订 schema
Day 6-8:   第一批 8 门 AAI 核心课双人标注（v1.3: 5→8）
Day 9:     Cohen's Kappa 一致性分析,争议字段开会（v1.3: 单独 1 天）
Day 10-13: 剩余 12 门课批量标注（v1.3: 4 天而非 4 天）
Day 14:    全量数据 LLM 自动抽取并与 Ground Truth 对比
```

> **Kappa 阈值**: ≥ 0.7 直接进 Week 3；0.5-0.7 修订指南后重标 1 门；< 0.5 schema 重新设计。

---

## 4. 评估集（100 条 v1.2 不变）

分层、指标、数据资产价值见 v1.2 §4。

---

## 5. 8 周详细排期（v1.3 最终版）

### Week 1: 基础设施 + Schema 设计 ✏️ 范围收缩

| 任务 | 负责 | 产出 |
|---|---|---|
| GitHub repo 初始化 + .gitignore + Push Protection | 全栈 | 仓库结构 |
| WSL2 Ubuntu 24.04 全员部署 + GPU passthrough 验证 | 全员 | docs/wsl2_setup.md |
| pydantic-settings 配置管理 | 后端 | config/settings.py |
| Schema v1 Pydantic 定义（含 schema_version） | 数据 | schemas/course.py |
| 标注指南文档 | 数据 | docs/annotation_guide.md |
| AAI 6600 单课 dry run | 全员 | 1 份完整 JSON |
| ADR 记录初始化（0001-0012） | 全栈 | docs/adr/ |
| ~~rclone 配置 + 备份脚本~~ | ~~全栈~~ | **→ 移至 Week 2** |

**Week 1 验收**: WSL2 环境统一 + Schema 验证通过 1 份 AAI 6600 JSON + repo 骨架可跑 lint/type check。

### Week 2: 数据采集层 + SQLite 初始化 + 备份机制

| 任务 | 负责 | 产出 |
|---|---|---|
| SQLite 初始化 + 建表脚本（含 course_aliases / users / user_unlocks） | 后端 | db/init.sql |
| NEU Course Catalog 爬虫（额外抓 cross-listed 字段） | 数据 | scrapers/neu_catalog.py |
| RateMyProfessors GraphQL 客户端 | 数据 | scrapers/rmp.py |
| Reddit PRAW 集成 | 后端 | scrapers/reddit.py |
| Syllabus PDF 收集 + PyMuPDF 解析 | 全栈 | scrapers/syllabus.py |
| 8 门 AAI 课双人标注（v1.3） | 全员 | 8 份 Ground Truth JSON |
| 团队人工录入 L2 别名（20 门课对应已知口语） | 全员 | data/aliases_manual.json |
| **rclone 配置 + backup.sh + crontab** | **全栈** | scripts/backup.sh |
| **备份脚本恢复演练（端到端验证）** | **全栈** | 演练记录 |
| **Latency 基线测试（Windows 路径 vs WSL2 路径）** | **后端** | docs/path_decision.md |

**Week 2 验收**: `python -m scrapers.run --course "AAI 6600"` 自动入库 + 别名表 ≥ 50 条 + 备份恢复成功 + 路径策略定案。

### Week 3: LLM 抽取 Pipeline

| 任务 | 负责 | 产出 |
|---|---|---|
| Gemini 2.5 Flash 客户端封装 | 后端 | llm/gemini_client.py |
| Review XML 包装函数 | 后端 | llm/formatter.py |
| 抽取 Prompt v1 + few-shot examples | 全员 | prompts/extract_v1.py |
| Pydantic 强约束输出 | 后端 | structured output 配置 |
| LLM 别名发现钩子（L3 别名,默认 pending） | 后端 | llm/alias_detector.py |
| 别名待审核队列简易 UI | 全栈 | Streamlit 子页面 |
| **Prompt A/B 对比工具**（v1.3 新增） | **后端** | **eval/compare_prompts.py** |
| 剩余 12 门课标注完成 | 全员 | 20 份 Ground Truth |

**Week 3 验收**: 自动抽取与 Ground Truth 字段一致率 ≥ 70% + 别名审核队列可用 + Prompt A/B 工具可对比 v1.0 vs v1.1。

### Week 4: RAG 检索引擎（含一致性兜底）

| 任务 | 负责 | 产出 |
|---|---|---|
| bge-m3 本地部署 + batch embedding | 数据 | rag/embedder.py |
| FAISS IndexIDMap 索引构建 | 后端 | rag/index.py |
| SQLite 硬过滤 + FAISS 白名单检索集成 | 后端 | rag/retriever.py |
| Query 归一化（走 v_course_lookup 视图） | 后端 | rag/query_normalizer.py |
| 评估集构建（100 条 query-course pairs） | 全员 | eval/test_set.json |
| Recall@5 / MRR 基础评估 | 数据 | eval/run_eval.py |
| **rebuild_faiss.py 兜底脚本**（v1.3 新增） | **后端** | **scripts/rebuild_faiss.py** |
| **Seed Data 收集启动**（v1.3 提前） | **产品** | data/coop_seed/ |

**Week 4 验收**:
- 主路径：Recall@5 ≥ 0.6 baseline + 双层架构跑通 + "5800" 类口语 query 能命中 CS 5800
- **悲观分支（v1.3 新增）**：若 Recall@5 < 0.5，Week 5 优先做 chunk 策略调优而非 HyDE

### Week 5: 高级检索 + 评估闭环

| 任务 | 负责 | 产出 |
|---|---|---|
| HyDE Query Expansion *或* Chunk 策略调优（取决于 Week 4 结果） | 后端 | rag/hyde.py *或* rag/chunker.py |
| 学生黑话词典（50 个映射） | 数据 | data/slang_dict.json |
| BM25 + 向量混合检索 | 后端 | rag/hybrid.py |
| Ragas 集成（三大指标） | 数据 | eval/ragas_runner.py |
| 评估 Dashboard | 数据 | Streamlit 子页面 |
| Co-op Schema 设计 + SQLite 表 | 全栈 | schemas/coop.py |
| PII 脱敏指南（含 k-anonymity 检查规则） | 产品 | docs/pii_redaction.md |

**Week 5 验收**: Recall@5 ≥ 0.75, Faithfulness ≥ 0.80 + 至少 15 条 Seed Data 入库。

### Week 6: 后端 API + Streamlit MVP + Seed Data 完成

| 任务 | 负责 | 产出 |
|---|---|---|
| FastAPI /search /course/{id} 端点 | 后端 | api/main.py |
| structlog JSON 日志全链路 | 后端 | api/logging.py |
| Google OAuth 集成（限定 NEU 域名） | 后端 | app/auth.py |
| Streamlit state_manager.py 标准模板 | 全栈 | app/state_manager.py |
| Streamlit Chat UI + Course Detail (st.write_stream) | 全栈 | app/streamlit_app.py |
| Evidence Snippets 引用气泡组件 | 全栈 | UI 组件 |
| 渐进式解锁 UI (Co-op 信息) + user_unlocks 持久化 | 全栈 | app/coop_view.py |
| Seed Data 全部入库 (≥ 30 条) | 产品 | 完整 Co-op 库 |
| 用户反馈按钮 (👍/👎 + 文本) | 全栈 | 反馈日志 |
| Cloudflare Tunnel 部署 | 全栈 | 公网可访问 URL |

**Week 6 验收**: 团队 3 人通过公网 URL 完成 ≥ 20 次端到端测试 + OAuth 限制生效（非 NEU 邮箱被拒）+ Seed Data 可见 + p50 latency < 1.5s。

### Week 7: 灰度发布 + Give-to-Get 飞轮

| 任务 | 负责 | 产出 |
|---|---|---|
| 邀请 30 位 NEU AAI 同学内测 | 全员 | 用户列表 |
| 真实 Query Log 分析 (structlog) | 数据 | 周报 |
| Co-op UGC 上传表单 | 全栈 | app/upload_coop.py |
| Give-to-Get 解锁逻辑 | 后端 | 简单积分系统 |
| Bug Fix + Schema v1.1 迭代（如需） | 全员 | 修订记录 |

**Week 7 验收**: 收集到 ≥ 200 条真实 query, ≥ 5 位核心贡献者，自然贡献率 ≥ 5%。

### Week 8: 数据分析 + 简历包装

同 v1.2 §5。

---

## 6. Seed Data 冷启动（v1.3 提前到 Week 4）

策略意义、数据来源合规、PII 脱敏标准、渐进式解锁设计、目标分布同 v1.2 §6。

**v1.3 新增 PII k-anonymity 规则**：
- 三元组 (公司类别, 岗位, 入学届) 在已发布 Seed Data 内必须 ≥ 2 条匹配
- 唯一三元组的 Seed 必须再做一层模糊化（如把"State Street"改成"Boston 大型资管"）

---

## 7. 工程规范（v1.2 不变）

仓库结构、路径规范、API Key 安全、代码质量、可观测性、Streamlit 状态管理 SOP、用户认证、数据备份、团队共识机制全部保留。

**v1.3 新增**：
- ADR-0013: SQLite 是真相源（一致性原则）
- ADR-0014: 项目代码 H 盘 + 运行时数据 WSL2 home（路径分离）

---

## 8-13. 成本预算 / 法律合规 / 风险预案 / 立即行动 / 决策日志 / v2 路线图

均与 v1.2 一致，立即行动清单按本文档 Week 1 范围调整。

### 立即行动清单（本周）修订

**Day 1（今天）**
- [ ] 创建 GitHub 仓库,设置 .gitignore + Push Protection
- [ ] 团队拉群确认 20 门 Ground Truth 课程清单
- [ ] 申请 Gemini API key（每人一个）
- [ ] 申请 Reddit API credentials
- [ ] 申请 Google OAuth Client ID（Google Cloud Console）
- [ ] 全员部署 WSL2 + 验证 GPU passthrough
- [ ] **每人下载自己上过的课的 syllabus PDF**（v1.3 新增，为 Day 3 dry run 备料）

**Day 2**
- [ ] Schema v1 Pydantic 定义完成（含 schema_version）
- [ ] 标注指南文档草稿
- [ ] 配置 pre-commit + detect-secrets
- [ ] SQLite 建表脚本 (courses + course_aliases + users + user_unlocks + coop_experiences)

**Day 3**
- [ ] AAI 6600 端到端 dry run（用 Day 1 晚下载的 syllabus）
- [ ] 收集第一批 5 门课的 syllabus PDF（补齐其他课）
- [ ] PII 脱敏指南草稿（为 Week 5 Seed Data 预热）
- [ ] 手动录入 AAI 6600 的所有已知别名作为 L2 数据样本

**Day 4-5（v1.3 新增）**
- [ ] 根据 dry run 修订 schema
- [ ] **rclone 配置（v1.3: 移到 Week 2 Day 4 而非 Day 1）**

---

**版本**: v1.3 **最后更新**: 2026-04-30 **下次评审**: Week 2 末
