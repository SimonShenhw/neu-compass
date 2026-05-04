"""Reddit PRAW integration for course mentions in r/csMajors / r/NEU.

PRAW (https://praw.readthedocs.io/) is the official Python wrapper around
Reddit's REST API. Per PLAN §9.1 Reddit access via PRAW with valid
credentials is fully ToS-clean.

Search strategy:
  For each subreddit in `subreddits`:
    - search(course_code, limit=limit_per_sub) returns submissions
    - for each submission, also walk its comment tree (replace_more(0) to
      keep things bounded) and pick comments that mention the code

Dedupe by post_id ('t3_xxx' / 't1_xxx'). Sort by score desc so the top-rated
mentions surface first.

PII (PLAN §3.4 / §6.3):
  - We do NOT capture or store `author` username. Public-but-PII.
  - body is stored verbatim — the caller is responsible for downstream PII
    scrubbing before any of this lands in a user-facing surface.
  - Permalinks are public + stable identifiers; OK to keep.

Live tests are gated by REDDIT_CLIENT_ID/SECRET. Fixture-backed unit tests
use the FakeReddit stand-in (see tests/test_scraper_reddit.py); production
runs against praw.Reddit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import logger

DEFAULT_SUBREDDITS: tuple[str, ...] = ("csMajors", "NEU")
DEFAULT_SEARCH_LIMIT = 25  # per subreddit; Reddit caps relevance ranking ~ this size


class RedditPost(BaseModel):
    """One Reddit submission OR comment mentioning a course."""

    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=1, description="t3_xxx (sub) or t1_xxx (comment)")
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
    reddit_client: Any | None = None,
) -> list[RedditPost]:
    """Search subreddits for posts + comments mentioning a course code.

    `reddit_client` may be a `praw.Reddit` instance (production) OR any
    duck-typed stand-in exposing `.subreddit(name).search(query, limit=N)`
    plus `submission.comments.replace_more(limit=0)` and `.list()`.
    Tests pass a FakeReddit; if None, we construct a real praw.Reddit
    from settings.
    """
    if reddit_client is None:
        reddit_client = _build_reddit_client()

    log = logger.bind(scraper="reddit", code=course_code)
    log.info("reddit.search.start", subreddits=list(subreddits))

    posts: list[RedditPost] = []
    seen: set[str] = set()
    needle = course_code.lower()

    for sub_name in subreddits:
        try:
            subreddit = reddit_client.subreddit(sub_name)
            submissions = list(subreddit.search(course_code, limit=limit_per_sub))
        except Exception as e:
            log.warning("reddit.search_failed", subreddit=sub_name, error=repr(e))
            continue

        for submission in submissions:
            sub_post = _submission_to_post(submission)
            if sub_post.post_id in seen:
                continue
            seen.add(sub_post.post_id)
            posts.append(sub_post)

            try:
                # replace_more(limit=0) drops "load more" stubs — bounded cost.
                submission.comments.replace_more(limit=0)
                comments = submission.comments.list()
            except Exception as e:
                log.warning(
                    "reddit.comments_failed",
                    submission_id=getattr(submission, "id", "?"),
                    error=repr(e),
                )
                continue

            for comment in comments[:limit_per_sub]:
                body = (getattr(comment, "body", "") or "")
                if needle not in body.lower():
                    continue
                cmt_post = _comment_to_post(comment)
                if cmt_post.post_id in seen:
                    continue
                seen.add(cmt_post.post_id)
                posts.append(cmt_post)

    posts.sort(key=lambda p: p.score, reverse=True)
    log.info("reddit.search.done", count=len(posts))
    return posts


def _build_reddit_client() -> Any:
    """Construct a real `praw.Reddit` from settings. Lazy-imports praw so that
    test-only paths (which pass a stand-in) don't drag in the dep at import."""
    from config import settings  # noqa: PLC0415
    import praw  # noqa: PLC0415

    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
        check_for_async=False,
    )


def _submission_to_post(submission: Any) -> RedditPost:
    """PRAW Submission → RedditPost. Defensive against missing attrs."""
    sub_obj = getattr(submission, "subreddit", None)
    sub_name = getattr(sub_obj, "display_name", None) or str(sub_obj or "")
    return RedditPost(
        post_id=f"t3_{submission.id}",
        subreddit=sub_name,
        body=getattr(submission, "selftext", "") or "",
        title=getattr(submission, "title", None),
        score=int(getattr(submission, "score", 0) or 0),
        created_utc=_to_utc_datetime(getattr(submission, "created_utc", 0)),
        permalink=getattr(submission, "permalink", ""),
        is_comment=False,
    )


def _comment_to_post(comment: Any) -> RedditPost:
    """PRAW Comment → RedditPost."""
    sub_obj = getattr(comment, "subreddit", None)
    sub_name = getattr(sub_obj, "display_name", None) or str(sub_obj or "")
    return RedditPost(
        post_id=f"t1_{comment.id}",
        subreddit=sub_name,
        body=getattr(comment, "body", "") or "",
        title=None,
        score=int(getattr(comment, "score", 0) or 0),
        created_utc=_to_utc_datetime(getattr(comment, "created_utc", 0)),
        permalink=getattr(comment, "permalink", ""),
        is_comment=True,
    )


def _to_utc_datetime(ts: float | int) -> datetime:
    """Coerce PRAW's epoch float timestamp into tz-aware UTC datetime."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        # Fallback: epoch 0. Shouldn't happen for real PRAW data.
        return datetime.fromtimestamp(0, tz=timezone.utc)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SUBREDDITS",
    "RedditPost",
    "search_course_mentions",
]
