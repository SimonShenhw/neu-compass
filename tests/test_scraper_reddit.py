"""Tests for scrapers.reddit using a FakeReddit stand-in.

Reddit credentials are not exercised in CI (Q3=mock per the Week 6+ plan).
The duck-typed FakeReddit mirrors only the praw.Reddit attribute surface
that search_course_mentions actually touches:

    reddit.subreddit(name).search(query, limit=N) -> list[FakeSubmission]
    submission.comments.replace_more(limit=0)     -> no-op
    submission.comments.list()                    -> list[FakeComment]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pytest

from scrapers.reddit import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SUBREDDITS,
    RedditPost,
    _comment_to_post,
    _submission_to_post,
    _to_utc_datetime,
    search_course_mentions,
)


# === Pydantic shape (kept here after stub graduation) ===


def test_post_minimal() -> None:
    p = RedditPost(
        post_id="t3_abc",
        subreddit="csMajors",
        body="how is AAI 6600?",
        created_utc=_to_utc_datetime(1714521600),
        permalink="/r/csMajors/comments/abc/",
    )
    assert p.is_comment is False
    assert p.title is None


def test_post_id_required_nonempty() -> None:
    with pytest.raises(ValueError):
        RedditPost(
            post_id="",
            subreddit="x",
            body="x",
            created_utc=_to_utc_datetime(0),
            permalink="x",
        )


def test_post_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        RedditPost(  # type: ignore[call-arg]
            post_id="t1_x", subreddit="x", body="x",
            created_utc=_to_utc_datetime(0), permalink="x",
            unexpected="boom",
        )


def test_default_subreddits_constant() -> None:
    assert "csMajors" in DEFAULT_SUBREDDITS
    assert "NEU" in DEFAULT_SUBREDDITS


def test_default_search_limit_positive() -> None:
    assert DEFAULT_SEARCH_LIMIT >= 1


# === FakeReddit stand-in ===


@dataclass
class _FakeSubObj:
    display_name: str

    def __str__(self) -> str:
        return self.display_name


@dataclass
class _FakeComments:
    items: list["_FakeComment"] = field(default_factory=list)

    def replace_more(self, limit: int = 0) -> None:  # noqa: ARG002
        return None

    def list(self) -> list["_FakeComment"]:
        return list(self.items)


@dataclass
class _FakeComment:
    id: str
    body: str
    score: int
    created_utc: float
    permalink: str
    subreddit: _FakeSubObj


@dataclass
class _FakeSubmission:
    id: str
    title: str
    selftext: str
    score: int
    created_utc: float
    permalink: str
    subreddit: _FakeSubObj
    comments: _FakeComments = field(default_factory=_FakeComments)


@dataclass
class _FakeSubreddit:
    name: str
    submissions: list[_FakeSubmission] = field(default_factory=list)
    last_search: tuple[str, int] | None = None

    def search(self, query: str, *, limit: int | None = None) -> Iterable[_FakeSubmission]:
        self.last_search = (query, limit or 0)
        return list(self.submissions)


@dataclass
class _FakeReddit:
    subreddits: dict[str, _FakeSubreddit] = field(default_factory=dict)
    last_subreddit_arg: str | None = None

    def subreddit(self, name: str) -> _FakeSubreddit:
        self.last_subreddit_arg = name
        return self.subreddits.setdefault(name, _FakeSubreddit(name=name))


def _make_post(
    *, sub: str, sid: str = "abc", body: str = "discussion of AAI 6600",
    title: str = "AAI 6600 thoughts", score: int = 5,
    comments: list[_FakeComment] | None = None,
) -> _FakeSubmission:
    sub_obj = _FakeSubObj(display_name=sub)
    return _FakeSubmission(
        id=sid, title=title, selftext=body, score=score,
        created_utc=1714521600.0,  # 2024-04-30 UTC
        permalink=f"/r/{sub}/comments/{sid}/",
        subreddit=sub_obj,
        comments=_FakeComments(items=comments or []),
    )


def _make_comment(*, sub: str, cid: str, body: str, score: int = 1) -> _FakeComment:
    return _FakeComment(
        id=cid, body=body, score=score, created_utc=1714525200.0,
        permalink=f"/r/{sub}/comments/parent/{cid}/",
        subreddit=_FakeSubObj(display_name=sub),
    )


# === Submission/Comment → RedditPost mapping ===


def test_submission_to_post_maps_canonical_fields() -> None:
    s = _make_post(sub="csMajors", sid="abc123", body="hi", title="t", score=42)
    p = _submission_to_post(s)
    assert p.post_id == "t3_abc123"
    assert p.subreddit == "csMajors"
    assert p.body == "hi"
    assert p.title == "t"
    assert p.score == 42
    assert p.is_comment is False
    assert p.permalink.endswith("abc123/")


def test_comment_to_post_marks_is_comment() -> None:
    c = _make_comment(sub="NEU", cid="x1", body="AAI 6600 was hard", score=3)
    p = _comment_to_post(c)
    assert p.post_id == "t1_x1"
    assert p.is_comment is True
    assert p.title is None
    assert "AAI 6600" in p.body


# === search_course_mentions end-to-end with FakeReddit ===


def test_search_returns_matching_submissions() -> None:
    reddit = _FakeReddit()
    sub = reddit.subreddit("csMajors")
    sub.submissions.extend([
        _make_post(sub="csMajors", sid="a1", body="AAI 6600 review"),
        _make_post(sub="csMajors", sid="a2", body="other course"),
    ])
    posts = search_course_mentions(
        "AAI 6600",
        subreddits=("csMajors",),
        reddit_client=reddit,
    )
    # FakeSubreddit.search returns ALL submissions (it's a stub) — the route
    # accepts everything Reddit gave it; matching is up to RMP-side relevance.
    assert {p.post_id for p in posts} == {"t3_a1", "t3_a2"}
    assert all(p.subreddit == "csMajors" for p in posts)


def test_search_filters_comments_by_needle() -> None:
    """Submission yields all matches; comments are filtered to those mentioning code."""
    reddit = _FakeReddit()
    sub = reddit.subreddit("NEU")
    sub.submissions.append(_make_post(
        sub="NEU", sid="p1", body="discussion thread",
        comments=[
            _make_comment(sub="NEU", cid="c1", body="took AAI 6600 last term", score=10),
            _make_comment(sub="NEU", cid="c2", body="wholly unrelated", score=99),
            _make_comment(sub="NEU", cid="c3", body="AAI 6600 was great", score=5),
        ],
    ))

    posts = search_course_mentions(
        "AAI 6600",
        subreddits=("NEU",),
        reddit_client=reddit,
    )
    ids = {p.post_id for p in posts}
    assert "t3_p1" in ids       # submission always included
    assert "t1_c1" in ids       # comment matches → included
    assert "t1_c3" in ids
    assert "t1_c2" not in ids   # comment doesn't mention code → dropped


def test_search_dedupes_across_subreddits() -> None:
    """Same submission ID surfacing under two subs only counts once."""
    reddit = _FakeReddit()
    a = reddit.subreddit("csMajors")
    b = reddit.subreddit("NEU")
    shared = _make_post(sub="csMajors", sid="dup", body="AAI 6600")
    a.submissions.append(shared)
    b.submissions.append(shared)
    posts = search_course_mentions(
        "AAI 6600",
        subreddits=("csMajors", "NEU"),
        reddit_client=reddit,
    )
    assert [p.post_id for p in posts].count("t3_dup") == 1


def test_search_sorts_by_score_desc() -> None:
    reddit = _FakeReddit()
    sub = reddit.subreddit("csMajors")
    sub.submissions.extend([
        _make_post(sub="csMajors", sid="low", body="AAI 6600", score=1),
        _make_post(sub="csMajors", sid="high", body="AAI 6600", score=99),
        _make_post(sub="csMajors", sid="mid", body="AAI 6600", score=50),
    ])
    posts = search_course_mentions(
        "AAI 6600", subreddits=("csMajors",), reddit_client=reddit,
    )
    assert [p.score for p in posts] == [99, 50, 1]


def test_search_passes_query_and_limit_to_subreddit() -> None:
    reddit = _FakeReddit()
    reddit.subreddit("csMajors")  # ensure created
    search_course_mentions(
        "CS 5800",
        subreddits=("csMajors",),
        limit_per_sub=7,
        reddit_client=reddit,
    )
    sr = reddit.subreddits["csMajors"]
    assert sr.last_search == ("CS 5800", 7)


def test_search_continues_when_one_subreddit_fails() -> None:
    """One subreddit raising shouldn't tank the rest of the run."""

    class BoomSubreddit:
        def search(self, *args, **kwargs):  # noqa: ARG002
            raise RuntimeError("simulated 503")

    class PartiallyBrokenReddit:
        def __init__(self) -> None:
            self.good = _FakeSubreddit(name="NEU", submissions=[
                _make_post(sub="NEU", sid="ok1", body="AAI 6600"),
            ])

        def subreddit(self, name: str):  # noqa: D401
            return BoomSubreddit() if name == "csMajors" else self.good

    posts = search_course_mentions(
        "AAI 6600",
        subreddits=("csMajors", "NEU"),
        reddit_client=PartiallyBrokenReddit(),
    )
    assert {p.post_id for p in posts} == {"t3_ok1"}


def test_search_does_not_capture_author_pii() -> None:
    """RedditPost has no `author` field — guard the schema-level guarantee."""
    fields = set(RedditPost.model_fields.keys())
    assert "author" not in fields
    assert "username" not in fields
