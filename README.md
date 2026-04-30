# NEU-Compass

Course RAG + Co-op MVP for NEU AAI / DS / CS graduate students.

> 项目代号: NEU-Compass · MVP 周期: 8 周 · 团队: 2-3 人

## 核心价值

用结构化 + 语义检索解决留学生"选课信息黑箱"问题，以 Course RAG 为流量入口，沉淀 Co-op 求职数据。

## 快速开始

### 环境前置

- WSL2 Ubuntu 24.04（FAISS / vLLM / Playwright 在 Windows 原生有玄学报错）
- Python 3.11+
- uv 包管理器
- NVIDIA GPU（bge-m3 本地 embed，5090 batch 速度 > 1k chunks/s）

### 路径策略（重要）

项目代码 checkout 在 H:\neu-compass（方便 Windows 编辑 + 备份）。
但**运行时数据** (FAISS index, SQLite db) 建议放 WSL2 home `~/neu-compass-data/`，避免 9P 跨文件系统 I/O 损耗。

通过 `.env` 控制：

```bash
# Windows 编辑环境
SQLITE_PATH=H:/neu-compass/data/courses.db
FAISS_INDEX_PATH=H:/neu-compass/data/faiss_index

# WSL2 运行环境（推荐）
SQLITE_PATH=/home/<你的用户名>/neu-compass-data/courses.db
FAISS_INDEX_PATH=/home/<你的用户名>/neu-compass-data/faiss_index
```

Week 2 末做一次 latency 对比，择优。

### 安装

```bash
# 在 WSL2 中
cd /mnt/h/neu-compass
uv sync
uv run pre-commit install
```

### 配置

```bash
cp .env.example .env
# 填入个人的 Gemini / Reddit / Google OAuth keys
```

## 文档

- 完整规划: [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md)
- ADR 决策记录: [docs/adr/](docs/adr/)
- 标注指南: docs/annotation_guide.md (Day 2 产出)
- WSL2 配置: docs/wsl2_setup.md (Day 1 产出)

## 仓库结构

见 [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) 第 7.1 节。

## 红线

- F1 合规：不商业化，不收款，不接受投资（详见 PLAN §9）
- 不爬 NUworks / Trace / RMP HTML（用 GraphQL endpoint）
- 个人 API key 独立，不共享
- 任何 commit 前 `git diff --cached` 自检

## 团队共识

- Standup: 每周一晚 30 分钟硬上限
- Code Review SLA: 24 小时超时自动合并
- 每个重大决策必须写 ADR

## 状态

v1.3 (2026-04-30) · MVP Week 0
