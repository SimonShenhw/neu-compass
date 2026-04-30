"""Reddit PRAW integration for r/csMajors / r/NEU course mentions.

PRAW (https://praw.readthedocs.io/) is the official Python wrapper around
Reddit's REST API. Unlike RMP / one-亩三分地, **Reddit is fully ToS-clean**
when accessed via PRAW with valid credentials (PLAN §9.1 marked as
compliance "low" risk).

== STATUS: SCAFFOLD ==

Interface (RedditPost + search_course_mentions) is stable. Live impl needs
working API credentials in .env (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET /
REDDIT_USER_AGENT). Tests use a mock praw.Reddit object so we don't hit
the live API in CI.

Search strategy: per PLAN §1.2, the high-value subreddits are:
  - r/csMajors (general CS school discussion)
  - r/NEU (Northeastern-specific)
  - r/csMajors search filters by school name
We search by course code (e.g. "AAI 6600", "CS 5800") within each.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import logger

DEFAULT_SUBREDDITS = ("csMajors", "NEU")
DEFAULT_SEARCH_LIMIT = 25  # Reddit caps per-search; 25 is plenty for one course


class RedditPost(BaseModel):
    """One Reddit submission or comment mentioning a course."""

    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=1, description="Reddit `t3_xxx` (submission) or `t1_xxx` (comment)")
    subreddit: str
    body: str
    title: str | None = None  # comments have no title
    score: int = 0
    created_utc: datetime
    permalink: str
    is_comment: bool = False


def search_course_mentions(
    course_code: str,
    *,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = DEFAULT_SEARCH_LIMIT,
    reddit_client: object | None = None,  # praw.Reddit; typed as object to avoid hard dep
) -> list[RedditPost]:
    """Search subreddits for posts mentioning a course code.

    Returns submissions matching the code + comments mentioning it. Caller
    is responsible for downstream PII redaction (PLAN §6.3) before any of
    this lands in the Co-op data path.

    TODO(Week 2 live impl):
      1. If reddit_client is None, build via:
            import praw
            reddit_client = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )
      2. For each subreddit:
            sr = reddit_client.subreddit(name)
            for submission in sr.search(course_code, limit=limit_per_sub):
                yield as RedditPost (is_comment=False)
                for comment in submission.comments.list():
                    if course_code in comment.body:
                        yield as RedditPost (is_comment=True)
      3. Dedupe by post_id (same post can show up across sub searches).
      4. Sort by score descending — top-rated mentions first.

    Rate limit: PRAW handles backoff automatically per Reddit's headers.
    """
    raise NotImplementedError(
        "scrapers.reddit.search_course_mentions: live PRAW impl pending. "
        "See module docstring TODO. Tests use a mock Reddit client."
    )


def _submission_to_post(submission: object) -> RedditPost:
    """Map PRAW Submission -> RedditPost. Pure function."""
    raise NotImplementedError("scrapers.reddit._submission_to_post: pending")


def _comment_to_post(comment: object) -> RedditPost:
    """Map PRAW Comment -> RedditPost. Pure function."""
    raise NotImplementedError("scrapers.reddit._comment_to_post: pending")


__all__ = [
    "DEFAULT_SUBREDDITS",
    "DEFAULT_SEARCH_LIMIT",
    "RedditPost",
    "search_course_mentions",
]
