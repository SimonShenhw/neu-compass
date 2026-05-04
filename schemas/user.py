"""User schema (Google OAuth, PLAN §7.7).

Mirrors db.init.sql users table 1:1. user_id is Google's `sub` claim
(stable across email changes). domain is parsed from email at write time
and used for the NEU-only whitelist (PLAN §3.5 / §3.6).

contribution_count drives the give-to-get gate (PLAN §6.4) — see
schemas.coop visibility_level + CoopRepository.list_visible_to_user.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """One authenticated NEU user."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, description="Google sub claim")
    email: str = Field(min_length=1)
    domain: str = Field(min_length=1, description="husky.neu.edu / northeastern.edu")
    display_name: str | None = None
    contribution_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None  # set by DB
    last_login_at: datetime | None = None


__all__ = ["User"]
