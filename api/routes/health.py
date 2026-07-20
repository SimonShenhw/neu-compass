"""/health (process liveness) and /ready (state-loaded readiness).

/health（进程存活）与 /ready（状态加载完毕的就绪检查）。

Cloudflare Tunnel + load-balancer pattern: /health is for "is the process
alive at all" (used by docker / systemd healthcheck); /ready is for "are
the model + index loaded yet" (used by orchestrator before routing
traffic). The 70s cold start (PLAN_v2.0 §2.5) means /ready returns
'warming' for ~70s after process start.

Cloudflare Tunnel + 负载均衡的模式：/health 回答"进程本身是否还活着"
（供 docker / systemd healthcheck 使用）；/ready 回答"模型与索引是否已
加载完毕"（供编排器在放行流量前使用）。70 秒冷启动（PLAN_v2.0 §2.5）
意味着 /ready 在进程启动后约 70 秒内会一直返回 'warming'。
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
    # 中文：真正的就绪不变式 —— 仅凭 `ready` 标志位还不够，需要防范这样一种
    # 部分初始化状态：lifespan 已经把 `ready` 设为 True，但某个关键组件仍是
    # None（这是在为将来可能把 lifespan 拆成更小步骤的重构做防御）。
    # Reranker 是可选的（/search 支持降级模式），所以不在不变式里 ——
    # 只有嵌入器 + FAISS + BM25 全部就绪，编排器才应该放行流量。
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
