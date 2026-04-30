# ADR-0001: 选择 SQLite + FAISS 而非 Milvus

## 状态

Accepted - 2026-04-29

## 背景

MVP 阶段需要选择 RAG 存储方案。规模预估：8 周内 ≤ 几万级 chunks。

## 决策

SQLite (文档库) + FAISS in-memory (向量库) 双层存储。
SQLite 用 JSON1 扩展存 metadata + raw_text + generated_json；FAISS 用 IndexIDMap 存 vector + course_id（不存 raw_text）。

## 拒绝的备选

- **Milvus**: 几万级 chunk 用不上分布式，Docker 增加复杂度
- **单一 FAISS**: 不擅长存 raw_text，metadata 过滤弱
- **PostgreSQL + pgvector**: 配置成本高于 MVP 收益，0 配置的 SQLite 更适合 8 周节奏

## 后果

- ✅ 0 配置 + 单文件备份（cp file.db 或 sqlite3 .backup）
- ✅ SQLite JSON1 索引可做硬过滤（WHERE term=? AND credits=?）
- ✅ FAISS IDSelectorBatch 实现白名单检索
- ⚠️ 数据规模 > 50w 行后需迁移到 PostgreSQL + Qdrant（v2 路线图）
- ❌ SQLite 单文件 + FAISS in-memory 是单点故障 → 必须配合 rclone 每日备份

## 触发重新评审的条件

- SQLite 单表 > 50w 行
- 多人写入冲突频繁出现
- 需要分布式部署
