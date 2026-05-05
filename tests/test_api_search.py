"""Tests for api.routes.search — alias-first then HybridRetriever fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient


# === Alias path ===


def test_search_alias_resolves_slang(api_client: TestClient) -> None:
    """'Algo' is a seeded slang alias for c-cs-5800 → alias path returns it."""
    r = api_client.post("/search", json={"query": "Algo", "k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "alias"
    assert body["query"] == "Algo"
    assert len(body["results"]) == 1
    hit = body["results"][0]
    assert hit["course_id"] == "c-cs-5800"
    assert hit["primary_code"] == "CS 5800"
    assert hit["matched_via"] == "alias"
    assert hit["score"] == 1.0


def test_search_alias_resolves_canonical_code(api_client: TestClient) -> None:
    """The query_normalizer regex strips/normalizes 'CS 5800' / 'cs5800' →
    primary_code lookup via v_course_lookup view."""
    for q in ["CS 5800", "cs5800"]:
        r = api_client.post("/search", json={"query": q, "k": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["matched_via"] == "alias", f"failed for {q!r}"
        assert body["results"][0]["course_id"] == "c-cs-5800"


# === Hybrid fallback ===


def test_search_hybrid_falls_through_when_no_alias(api_client: TestClient) -> None:
    """A natural-language query with no alias hit goes through HybridRetriever.
    BM25 should rank c-cs-5800 first for 'graph algorithms BFS' since it's the
    only course with those tokens in raw_text."""
    r = api_client.post("/search", json={"query": "graph algorithms BFS", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "hybrid"
    assert len(body["results"]) >= 1
    assert body["results"][0]["course_id"] == "c-cs-5800"
    assert body["results"][0]["matched_via"] == "hybrid"


def test_search_hybrid_lexical_match_for_ml(api_client: TestClient) -> None:
    """Same path, different course: 'neural network backpropagation' → DS 5220."""
    r = api_client.post(
        "/search",
        json={"query": "neural network backpropagation training", "k": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "hybrid"
    assert body["results"][0]["course_id"] == "c-ds-5220"


# === Hard filters ===


def test_search_hard_filter_term(api_client: TestClient) -> None:
    """term='Fall 2025' should restrict to c-ds-5220; CS 5800 / AAI 6600 are
    Spring 2026 in the seed."""
    r = api_client.post(
        "/search",
        json={
            "query": "neural network",  # natural-lang → hybrid path
            "k": 5,
            "term": "Fall 2025",
        },
    )
    assert r.status_code == 200
    body = r.json()
    course_ids = {hit["course_id"] for hit in body["results"]}
    assert course_ids <= {"c-ds-5220"}


def test_search_invalid_delivery_mode_returns_422(api_client: TestClient) -> None:
    r = api_client.post(
        "/search",
        json={"query": "graph algorithms", "delivery_mode": "telepathy"},
    )
    assert r.status_code == 422


# === Validation ===


def test_search_empty_query_returns_422(api_client: TestClient) -> None:
    r = api_client.post("/search", json={"query": "", "k": 5})
    assert r.status_code == 422


def test_search_query_too_long_returns_422(api_client: TestClient) -> None:
    r = api_client.post("/search", json={"query": "x" * 501})
    assert r.status_code == 422


def test_search_k_out_of_range_returns_422(api_client: TestClient) -> None:
    r = api_client.post("/search", json={"query": "graph", "k": 100})
    assert r.status_code == 422


def test_search_extra_field_rejected(api_client: TestClient) -> None:
    """SearchRequest is extra='forbid' — typo'd fields fail loud, not silent."""
    r = api_client.post(
        "/search",
        json={"query": "graph", "kk": 5},  # 'kk' not 'k'
    )
    assert r.status_code == 422


# === Response shape ===


def test_search_response_has_latency_ms(api_client: TestClient) -> None:
    r = api_client.post("/search", json={"query": "graph algorithms"})
    assert r.status_code == 200
    body = r.json()
    assert "latency_ms" in body
    assert isinstance(body["latency_ms"], (int, float))
    assert body["latency_ms"] >= 0


def test_search_empty_when_no_match(api_client: TestClient) -> None:
    """A query with no alias hit and no BM25 vocab overlap should still return
    something from the vector leg (deterministic insertion order in the
    FixtureEmbedder), but matched_via='hybrid' (not 'empty') because the
    vector leg always returns something. To get matched_via='empty', filters
    must drop the entire candidate set."""
    r = api_client.post(
        "/search",
        json={
            "query": "wholly unrelated woodworking topic",
            "term": "Summer 2099",  # no course matches
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "empty"
    assert body["results"] == []


# === Adversarial rejection (PLAN v2.2 §3.4) ===


def test_search_rejects_query_with_no_corpus_overlap(api_client: TestClient) -> None:
    """An adversarial query whose tokens don't overlap any candidate text
    has max(reranker_sigmoid) = 0 < threshold 0.4 → matched_via='rejected'
    with empty results and a populated rejection_reason."""
    r = api_client.post(
        "/search",
        json={"query": "ancient roman emperors and empires", "k": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "rejected"
    assert body["results"] == []
    assert body["rejection_reason"] is not None
    assert "max_reranker_sigmoid" in body["rejection_reason"]


def test_search_legitimate_query_passes_rejection_gate(api_client: TestClient) -> None:
    """A query with token overlap to one of the indexed courses has max
    sigmoid above threshold → matched_via='hybrid', not 'rejected'."""
    r = api_client.post(
        "/search",
        json={"query": "graph algorithms BFS shortest paths", "k": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "hybrid"
    assert body["rejection_reason"] is None
    assert body["results"][0]["course_id"] == "c-cs-5800"


def test_search_rejection_reason_omitted_on_alias_path(api_client: TestClient) -> None:
    """Alias short-circuit doesn't go through the reranker; rejection_reason
    must remain None on alias hits."""
    r = api_client.post("/search", json={"query": "Algo", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "alias"
    assert body["rejection_reason"] is None
