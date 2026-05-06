"""/health (process liveness) and /ready (state-loaded readiness).

Cloudflare Tunnel + load-balancer pattern: /health is for "is the process
alive at all" (used by docker / systemd healthcheck); /ready is for "are
the model + index loaded yet" (used by orchestrator before routing
traffic). The 70s cold start (PLAN_v2.0 §2.5) means /ready returns
'warming' for ~70s after process start.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.models import HealthResponse, ReadyResponse

router = APIRouter(tags=["ops"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Process liveness",
    description=(
        "Always 200 if the process responds — does **not** check whether the "
        "embedder/reranker have warmed. Use `/ready` for that. Suitable for "
        "Cloudflare Tunnel / docker / systemd healthcheck."
    ),
)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Lifespan readiness (models warmed, indexes loaded)",
    description=(
        "Returns `status='ready'` once the lifespan startup hook completed: "
        "FAISS index loaded, BM25 corpus built, bge-m3 embedder warmed, "
        "bge-reranker-v2-m3 warmed. Returns `status='warming'` for ~70-100 "
        "seconds after process start (cold model load — see "
        "[PLAN_v2.0 §2.5](docs/PLAN_v2.0.md)).\n\n"
        "Orchestrators should wait for `ready` before routing user traffic."
    ),
)
async def ready(request: Request) -> ReadyResponse:
    state = request.app.state
    is_ready_flag = bool(getattr(state, "ready", False))
    faiss_index = getattr(state, "faiss_index", None)
    bm25_corpus = getattr(state, "bm25_corpus", None)
    embedder = getattr(state, "embedder", None)

    # Real readiness invariant: the `ready` flag alone isn't enough — guard
    # against a partially-initialized state where lifespan set `ready=True`
    # but a critical component is still None (defense against future
    # refactors that might split lifespan into smaller steps). Reranker is
    # optional (degraded-mode is supported by /search), so it's NOT in the
    # invariant — only embedder + FAISS + BM25 must all be live for
    # orchestrators to route traffic.
    is_actually_ready = (
        is_ready_flag
        and faiss_index is not None
        and faiss_index.count > 0
        and bm25_corpus is not None
        and bm25_corpus.count > 0
        and embedder is not None
    )

    return ReadyResponse(
        status="ready" if is_actually_ready else "warming",
        courses_indexed=faiss_index.count if faiss_index is not None else 0,
        bm25_corpus=bm25_corpus.count if bm25_corpus is not None else 0,
    )
