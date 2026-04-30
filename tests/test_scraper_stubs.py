"""Tests for scaffold scrapers — neu_catalog, rmp, reddit.

These scrapers are STATUS: SCAFFOLD (see module docstrings). Tests verify:
  1. Pydantic output models reject bad input + accept good input.
  2. Public functions raise NotImplementedError (no one accidentally runs
     them in production before the live impl lands).
  3. Module constants are present and well-formed.

When live impl lands (Week 2-3), replace the NotImplementedError tests
with mocked-transport / canned-JSON / mocked-PRAW tests at the same
public surface.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


# === neu_catalog ===

def test_neu_catalog_entry_minimal() -> None:
    from scrapers.neu_catalog import CatalogEntry
    e = CatalogEntry(course_code="AAI 6600", course_name="Applied AI")
    assert e.credits is None
    assert e.prereqs == []
    assert e.cross_listed_codes == []


def test_neu_catalog_entry_with_credits_bounds() -> None:
    from scrapers.neu_catalog import CatalogEntry
    CatalogEntry(course_code="CS 5800", course_name="Algo", credits=4)
    with pytest.raises(ValueError):
        CatalogEntry(course_code="CS 5800", course_name="Algo", credits=15)


def test_neu_catalog_entry_extra_forbidden() -> None:
    from scrapers.neu_catalog import CatalogEntry
    with pytest.raises(ValueError):
        CatalogEntry(course_code="CS 5800", course_name="Algo", unknown="x")


def test_neu_catalog_fetch_course_pending() -> None:
    """Live impl pending; should raise loud NotImplementedError, not silently no-op."""
    from scrapers.neu_catalog import fetch_course
    with pytest.raises(NotImplementedError, match="live HTTP impl pending"):
        fetch_course("AAI 6600")


def test_neu_catalog_base_url_constant() -> None:
    from scrapers.neu_catalog import CATALOG_BASE_URL
    assert CATALOG_BASE_URL == "https://catalog.northeastern.edu"


# === rmp ===

def test_rmp_review_minimal() -> None:
    from scrapers.rmp import RmpReview
    r = RmpReview(review_id="rmp_1", comment="Tough but fair")
    assert r.overall_rating is None


def test_rmp_review_rating_bounds() -> None:
    from scrapers.rmp import RmpReview
    RmpReview(review_id="r1", comment="x", overall_rating=4.5, difficulty_rating=3.0)
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", overall_rating=5.5)
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", overall_rating=-1)


def test_rmp_professor_summary_minimal() -> None:
    from scrapers.rmp import RmpProfessorSummary
    s = RmpProfessorSummary(professor_id="p1", name="Dr. Smith")
    assert s.reviews == []
    assert s.num_ratings == 0


def test_rmp_search_professor_pending() -> None:
    from scrapers.rmp import search_professor
    with pytest.raises(NotImplementedError, match="GraphQL impl pending"):
        search_professor("Dr. Smith")


def test_rmp_constants() -> None:
    from scrapers.rmp import RMP_GRAPHQL_URL, NEU_SCHOOL_ID
    assert RMP_GRAPHQL_URL.startswith("https://")
    assert NEU_SCHOOL_ID  # non-empty placeholder


def test_rmp_review_extra_forbidden() -> None:
    from scrapers.rmp import RmpReview
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", unexpected="x")


# === reddit ===

def test_reddit_post_minimal() -> None:
    from scrapers.reddit import RedditPost
    p = RedditPost(
        post_id="t3_abc",
        subreddit="csMajors",
        body="how is AAI 6600?",
        created_utc=datetime(2026, 4, 30, tzinfo=timezone.utc),
        permalink="/r/csMajors/comments/abc/",
    )
    assert p.is_comment is False
    assert p.title is None


def test_reddit_post_id_required_nonempty() -> None:
    from scrapers.reddit import RedditPost
    with pytest.raises(ValueError):
        RedditPost(
            post_id="",  # empty rejected
            subreddit="x",
            body="x",
            created_utc=datetime.now(timezone.utc),
            permalink="x",
        )


def test_reddit_post_extra_forbidden() -> None:
    from scrapers.reddit import RedditPost
    with pytest.raises(ValueError):
        RedditPost(
            post_id="t1_x", subreddit="x", body="x",
            created_utc=datetime.now(timezone.utc), permalink="x",
            unexpected="boom",
        )


def test_reddit_search_pending() -> None:
    from scrapers.reddit import search_course_mentions
    with pytest.raises(NotImplementedError, match="live PRAW impl pending"):
        search_course_mentions("AAI 6600")


def test_reddit_default_subreddits() -> None:
    from scrapers.reddit import DEFAULT_SUBREDDITS
    assert "csMajors" in DEFAULT_SUBREDDITS
    assert "NEU" in DEFAULT_SUBREDDITS
