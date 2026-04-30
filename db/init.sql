-- =============================================================================
-- NEU-Compass · SQLite schema v1.0 (Week 1 Day 2)
--
-- 设计要点:
--   - courses 是真相源 (ADR-0013), FAISS 仅是派生索引
--   - status 字段控制 embed pipeline 状态机 (pending -> indexed -> failed)
--   - 硬过滤字段走 JSON1 + indexed json_extract (PLAN §1.3)
--   - 软字段全在 generated_json, 不展开成列 (允许 schema 演进无需 ALTER TABLE)
--   - course_aliases 多对一指向 primary_course_id (PLAN §1.4)
--   - v_course_lookup 视图统一查询入口 (primary_code + 所有 approved 别名)
--
-- 重要: FK enforcement 是连接级开关, 应用代码每次连接必须执行:
--          PRAGMA foreign_keys = ON;
-- =============================================================================

PRAGMA journal_mode = WAL;  -- 持久化设置, 写入并发更友好

-- =============================================================================
-- 1. courses (主课程表)
-- =============================================================================

CREATE TABLE IF NOT EXISTS courses (
    course_id        TEXT PRIMARY KEY,                    -- 内部 UUID, 跨改名稳定
    primary_code     TEXT NOT NULL COLLATE NOCASE,        -- 'CS 5800' 等规范代码
    primary_name     TEXT NOT NULL,
    metadata         JSON NOT NULL,                       -- {term, credits, professor, prereqs, delivery_mode}
    raw_text         TEXT,                                -- 拼接源文本 (catalog + syllabus + reviews)
    generated_json   JSON NOT NULL,                       -- 完整 Course Pydantic dump
    schema_version   TEXT NOT NULL DEFAULT '1.0',
    status           TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'indexed', 'failed')),
    indexed_at       TIMESTAMP,                           -- FAISS 写入成功的时间戳
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_courses_term
    ON courses(json_extract(metadata, '$.term'));
CREATE INDEX IF NOT EXISTS idx_courses_credits
    ON courses(json_extract(metadata, '$.credits'));
CREATE INDEX IF NOT EXISTS idx_courses_primary_code
    ON courses(primary_code);
CREATE INDEX IF NOT EXISTS idx_courses_status
    ON courses(status);  -- 监控 pending 老化 (>24h 报警)

-- 自动维护 updated_at: 仅在用户没有显式改动 updated_at 时触发
-- (SQLite 默认 PRAGMA recursive_triggers=OFF, 不会无限递归)
DROP TRIGGER IF EXISTS trg_courses_updated_at;
CREATE TRIGGER trg_courses_updated_at
AFTER UPDATE ON courses
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE courses SET updated_at = CURRENT_TIMESTAMP
        WHERE course_id = NEW.course_id;
END;

-- =============================================================================
-- 2. course_aliases (别名映射表, PLAN §1.4)
--    类型:
--      cross_listed              CS 5800 ≈ DS 5000
--      version                   AAI 5000 -> AAI 6600
--      rename                    "Knowledge Engineering" -> "Knowledge Representation"
--      slang                     "5800" / "Algo" / "算法课" -> CS 5800
--      professor_attribution     "Prof. Zhang's ML" -> CS 6140
-- =============================================================================

CREATE TABLE IF NOT EXISTS course_aliases (
    alias_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_text         TEXT NOT NULL COLLATE NOCASE,
    alias_type         TEXT NOT NULL
                         CHECK (alias_type IN ('cross_listed', 'version', 'rename',
                                               'slang', 'professor_attribution')),
    primary_course_id  TEXT NOT NULL,
    confidence         REAL NOT NULL DEFAULT 1.0
                         CHECK (confidence >= 0.0 AND confidence <= 1.0),
    valid_from         DATE,
    valid_until        DATE,
    source             TEXT NOT NULL
                         CHECK (source IN ('official', 'manual', 'llm_inferred')),
    review_status      TEXT NOT NULL DEFAULT 'approved'
                         CHECK (review_status IN ('approved', 'pending', 'rejected')),
    evidence           TEXT,                              -- LLM 推断时存原文 (前 500 字)
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (primary_course_id) REFERENCES courses(course_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alias_text
    ON course_aliases(alias_text);
CREATE INDEX IF NOT EXISTS idx_alias_primary_id
    ON course_aliases(primary_course_id);
CREATE INDEX IF NOT EXISTS idx_alias_review_status
    ON course_aliases(review_status);

-- 同一别名同类型同 primary 不应重复
CREATE UNIQUE INDEX IF NOT EXISTS uq_alias_combo
    ON course_aliases(alias_text, alias_type, primary_course_id);

-- =============================================================================
-- 3. users (Google OAuth, PLAN §7.7)
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id              TEXT PRIMARY KEY,                -- Google sub claim
    email                TEXT UNIQUE NOT NULL,
    domain               TEXT NOT NULL,                   -- husky.neu.edu / northeastern.edu
    display_name         TEXT,
    contribution_count   INTEGER NOT NULL DEFAULT 0
                           CHECK (contribution_count >= 0),
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at        TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_domain ON users(domain);

-- =============================================================================
-- 4. user_unlocks (give-to-get 解锁记录, PLAN §7.7)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_unlocks (
    unlock_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,
    coop_id       TEXT NOT NULL,
    unlocked_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, coop_id)                            -- 防重复解锁
);

CREATE INDEX IF NOT EXISTS idx_user_unlocks_user
    ON user_unlocks(user_id);
CREATE INDEX IF NOT EXISTS idx_user_unlocks_coop
    ON user_unlocks(coop_id);

-- =============================================================================
-- 5. coop_experiences (Co-op UGC 数据, PLAN §1.4 / §6)
--    visibility_level:
--      0 = 钓鱼层公开预览 (公司+岗位+时间)
--      1 = 贡献 1 条解锁详细面试流程 / 技术面真题
--      2 = 贡献 2 条 + 邀请 1 人解锁 NEU 校友去向数据
-- =============================================================================

CREATE TABLE IF NOT EXISTS coop_experiences (
    coop_id              TEXT PRIMARY KEY,
    company              TEXT NOT NULL,
    role                 TEXT NOT NULL,
    related_courses      JSON,                            -- ["AAI 6600", "DS 5220"]
    interview_summary    TEXT,                            -- 已脱敏 (PLAN §6.3 标准)
    contributor_user_id  TEXT,                            -- NULL = seed data
    is_seed_data         INTEGER NOT NULL DEFAULT 0
                           CHECK (is_seed_data IN (0, 1)),  -- SQLite 没原生 BOOL
    visibility_level     INTEGER NOT NULL DEFAULT 0
                           CHECK (visibility_level IN (0, 1, 2)),
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (contributor_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_coop_company
    ON coop_experiences(company);
CREATE INDEX IF NOT EXISTS idx_coop_visibility
    ON coop_experiences(visibility_level);
CREATE INDEX IF NOT EXISTS idx_coop_is_seed
    ON coop_experiences(is_seed_data);

-- =============================================================================
-- 6. v_course_lookup (统一查询入口, PLAN §1.4)
--    用法: SELECT course_id FROM v_course_lookup WHERE searchable_term = ?
--    把 primary_code + 所有 approved 别名 union 成单一查询面
-- =============================================================================

DROP VIEW IF EXISTS v_course_lookup;
CREATE VIEW v_course_lookup AS
SELECT
    a.alias_text   AS searchable_term,
    a.alias_type,
    c.course_id,
    c.primary_code,
    c.primary_name
FROM course_aliases a
JOIN courses c ON a.primary_course_id = c.course_id
WHERE a.review_status = 'approved'
UNION ALL
SELECT
    primary_code   AS searchable_term,
    'primary'      AS alias_type,
    course_id,
    primary_code,
    primary_name
FROM courses;

-- =============================================================================
-- 7. schema_versions (DDL 版本审计)
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_versions (
    version      TEXT PRIMARY KEY,
    applied_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes        TEXT
);

INSERT OR IGNORE INTO schema_versions (version, notes)
VALUES ('1.0', 'Initial schema (Week 1 Day 2): courses + aliases + users + unlocks + coop');
