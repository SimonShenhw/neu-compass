# ADR-0014: 项目代码在 H 盘，运行时数据在 WSL2 home

## 状态

Proposed - 2026-04-30 (Week 2 末做 latency 实测后转 Accepted)

## 背景

v1.2 计划假设 PROJECT_ROOT = `/home/haowei/neu-compass`（纯 WSL2 路径），但实际开发环境项目代码 checkout 在 H:\neu-compass（Windows NTFS）。
WSL2 通过 9P 协议访问 `/mnt/h/` 有跨文件系统 I/O 损耗，对 SQLite 高频读写 + FAISS index mmap 不友好。

## 决策

**代码与运行时数据物理分离**：

| 资产 | 位置 | 理由 |
|---|---|---|
| 源代码 / docs / tests | H:\neu-compass | Windows 编辑友好 + 易备份 + Git 操作 |
| SQLite db | ~/neu-compass-data/ (WSL2 home) | 高频写入，避免跨 fs I/O |
| FAISS index | ~/neu-compass-data/ (WSL2 home) | mmap 性能 |
| Embedding cache | ~/neu-compass-data/ | 几 GB 级别，避免污染 git |
| Backups (rclone target) | H:\neu-compass\backups\ | 跨设备可恢复 |

通过 `.env` 的 `SQLITE_PATH` / `FAISS_INDEX_PATH` 控制。

## 拒绝的备选

- **全部放 H 盘**: WSL2 跨 fs I/O 损耗实测可达 5-10x（待 Week 2 验证）
- **全部放 WSL2 home**: Windows 编辑器（VS Code / PyCharm）需走 WSL Remote 协议，团队 onboarding 增加复杂度
- **放 OneDrive**: 文件锁定 + 同步冲突 + 隐私

## 后果

- ✅ 编辑代码用 Windows 工具，运行用 WSL2，I/O 各取所长
- ⚠️ 团队成员 onboarding 时需要正确设置两套路径
- ⚠️ 备份脚本要同时拉 H:\neu-compass + ~/neu-compass-data/
- ❌ 单一路径假设的代码会出错（强制走 PROJECT_ROOT 环境变量，不允许硬编码）

## 触发重新评审的条件

- Week 2 末 latency 实测显示纯 H 盘和分离方案差距 < 20%（差距小则简化为单路径）
- 团队普遍抱怨 onboarding 复杂

## Week 2 验证脚本

待 Week 2 写：`scripts/bench_path.py` 跑 1k 次 SQLite 写 + 1k 次 FAISS 查询，对比 H:\ 路径与 WSL2 home 路径。
