# ADR-0013: SQLite 是唯一真相源（FAISS 可重建）

## 状态

Accepted - 2026-04-30

## 背景

MVP 早期 v1.2 计划没有规定 SQLite 与 FAISS 之间的写入顺序与一致性边界。
潜在故障场景：爬虫写完 SQLite 后 embed 失败 → FAISS 没数据但 SQLite 有 → 检索时 FAISS 命中 course_id 但 SQLite 回查找不到（或反过来）。
没有恢复路径意味着脱节后只能手动核对，规模一上来必然咬人。

## 决策

1. **SQLite 是唯一真相源**：所有持久化数据写入流程从 SQLite 开始，FAISS 是派生索引。
2. **写入流程标准化**：
   ```
   SQLite INSERT (status='pending')
     → embed
     → FAISS add_with_ids
     → SQLite UPDATE status='indexed'
   ```
3. **rebuild_faiss.py 兜底脚本**：可从 SQLite `WHERE status='indexed'` 全量重建 FAISS index，作为故障恢复路径。
4. **启动检查**：服务启动时校验 FAISS 中所有 ID 都在 SQLite 中且 status='indexed'，不一致则记日志并触发重建。

## 拒绝的备选

- **两阶段提交**: 跨 SQLite + FAISS 的分布式事务，对 MVP 是过度工程
- **不做兜底**: 一旦脱节就要手动修，规模上来不可持续

## 后果

- ✅ 任意时刻挂掉，重启后可一致性恢复
- ✅ FAISS index 文件丢失 → `python -m scripts.rebuild_faiss` 即可
- ⚠️ 写入路径多一次 SQLite UPDATE
- ❌ 中间 status='pending' 的行不会出现在检索结果，需要监控 pending 老化（>24h 报警）

## 触发重新评审的条件

- SQLite 写入 IOPS 成为瓶颈
- 需要事务级别的强一致性（金融场景才需要）
