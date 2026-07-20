"""User schema (Google OAuth, PLAN §7.7).

Mirrors db.init.sql users table 1:1. user_id is Google's `sub` claim
(stable across email changes). domain is parsed from email at write time
and used for the NEU-only whitelist (PLAN §3.5 / §3.6).

与 db.init.sql 中的 users 表一一对应。user_id 是 Google 的 `sub` 声明
(claim)(邮箱变更后依然保持不变)。domain 在写入时从 email 解析得到,
用于"仅限 NEU"的白名单校验(PLAN §3.5 / §3.6)。

contribution_count drives the give-to-get gate (PLAN §6.4) — see
schemas.coop visibility_level + CoopRepository.list_visible_to_user.

contribution_count 驱动"贡献换权限"(give-to-get)门槛机制(PLAN §6.4)
—— 参见 schemas.coop 的 visibility_level 以及
CoopRepository.list_visible_to_user。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """One authenticated NEU user.

    中文:一个经过身份验证的 NEU 用户。
    """

    model_config = ConfigDict(extra="forbid")

    # 中文:Google 的 sub 声明(claim)
    user_id: str = Field(min_length=1, description="Google sub claim")
    email: str = Field(min_length=1)
    # 中文:husky.neu.edu / northeastern.edu
    domain: str = Field(min_length=1, description="husky.neu.edu / northeastern.edu")
    display_name: str | None = None
    contribution_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None  # set by DB
    # 中文:由数据库设置
    last_login_at: datetime | None = None


__all__ = ["User"]
