"""Program ontology schemas (PLAN v3.0 Layer 3).

A `Program` is a NEU master's / bachelor's program (e.g. AAI MS, CS Align,
DS MS). It links to courses via `ProgramRequiredCourse`, which carries the
"how does this course fit into the program" annotation: requirement_type
(core / foundation / elective / capstone) and an optional
semester_recommended.

`Program` 是 NEU 的一个硕士 / 本科专业(如 AAI MS、CS Align、DS MS)。
它通过 `ProgramRequiredCourse` 与课程关联,后者携带"这门课在专业里扮演
什么角色"的注解:requirement_type(core / foundation / elective /
capstone)以及可选的 semester_recommended。

The chat route uses these to answer queries like "我是 AAI 专业，第一学期
选什么" deterministically — no hybrid retrieval guess-work.

聊天路由用这些数据确定性地(deterministically)回答类似"我是 AAI 专业,
第一学期选什么"这样的查询 —— 不需要依赖混合检索去"猜"。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 中文:课程在专业培养方案中扮演的角色类型
RequirementType = Literal["core", "foundation", "elective_pool", "capstone"]
# 中文:先修课要求的强度
PrereqRequirement = Literal["required", "recommended", "concurrent"]


class Program(BaseModel):
    """A degree program (Master's / Bachelor's). prefix links to
    `courses.primary_code` — e.g. prefix='AAI' covers all 'AAI 5xxx/6xxx'.

    中文:一个学位专业(硕士 / 本科)。prefix 与 `courses.primary_code`
    关联 —— 例如 prefix='AAI' 覆盖所有 'AAI 5xxx/6xxx' 课程。
    """

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1)
    # 中文:课程代码前缀;大写。用于检索的预过滤(pre-filter)。
    prefix: str = Field(
        min_length=1, max_length=10,
        description="Course-code prefix; uppercase. Used for retrieval pre-filter.",
    )
    department: str | None = None
    college: str | None = None
    notes: str | None = None


class ProgramRequiredCourse(BaseModel):
    """Edge: program -> course with annotation. semester_recommended=1 means
    'recommended for the first semester of this program'.

    中文:一条"专业 -> 课程"的边,带注解。semester_recommended=1 表示
    "建议在本专业的第一学期修读"。
    """

    model_config = ConfigDict(extra="forbid")

    program_id: str
    course_id: str
    requirement_type: RequirementType
    semester_recommended: int | None = Field(default=None, ge=1, le=8)
    notes: str | None = None


class CoursePrerequisite(BaseModel):
    """Edge: course X requires having taken prereq_course_id first.

    中文:一条"课程 X 要求先修 prereq_course_id"的边。
    """

    model_config = ConfigDict(extra="forbid")

    course_id: str
    prereq_course_id: str
    requirement: PrereqRequirement = "required"
    notes: str | None = None


__all__ = [
    "CoursePrerequisite",
    "PrereqRequirement",
    "Program",
    "ProgramRequiredCourse",
    "RequirementType",
]
