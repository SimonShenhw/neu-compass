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


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Always 200 if the process responds — no state checks."""
    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """200 with status='ready' once lifespan finished; 'warming' before."""
    state = request.app.state
    is_ready = bool(getattr(state, "ready", False))
    faiss_index = getattr(state, "faiss_index", None)
    bm25_corpus = getattr(state, "bm25_corpus", None)
    return ReadyResponse(
        status="ready" if is_ready else "warming",
        courses_indexed=faiss_index.count if faiss_index is not None else 0,
        bm25_corpus=bm25_corpus.count if bm25_corpus is not None else 0,
    )
