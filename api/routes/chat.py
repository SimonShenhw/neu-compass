"""POST /chat — streamed grounded course advisor (Week 6 PLAN §4.1).

Pipeline:
  query
    → query_normalizer → AliasRepository.resolve  (cheap exact path)
    → HybridRetriever.search (k=5 by default)     (semantic fallback)
    → llm.prompts.chat_v1.build_prompt
    → Gemini stream (token-by-token)

Wire format: NDJSON. One JSON object per line, chunks of:
  {"type": "meta",  "matched_via": "alias|hybrid|empty",
                    "results": [{"course_id", "primary_code", "primary_name", "score"}]}
  {"type": "token", "text": "..."}     (zero or more)
  {"type": "error", "detail": "..."}   (only on Gemini failure)
  {"type": "done"}                     (always last)

Streamlit consumes via httpx.stream + iter_lines + st.write_stream.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator as _Iter
from typing import Annotated, Any, Callable, Iterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.dependencies import (
    get_alias_repo,
    get_chat_stream_fn,
    get_course_repo,
    get_hybrid_retriever,
)
from api.models import ChatRequest
from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from llm.gemini_client import GeminiError
from llm.prompts.chat_v1 import build_prompt
from rag.hybrid import HybridRetriever
from rag.query_normalizer import normalize_query_to_course_ids
from rag.retriever import SearchHit
from schemas.course import DeliveryMode

router = APIRouter(prefix="/chat", tags=["chat"])

log = structlog.get_logger("neu_compass.chat")


@router.post("")
async def chat(
    req: ChatRequest,
    alias_repo: Annotated[AliasRepository, Depends(get_alias_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    hybrid: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    stream_fn: Annotated[
        Callable[[str], _Iter[str]],
        Depends(get_chat_stream_fn),
    ],
) -> StreamingResponse:
    """Stream a Gemini-generated answer grounded in the retrieved courses."""
    if req.delivery_mode is not None:
        try:
            DeliveryMode(req.delivery_mode)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid delivery_mode: {req.delivery_mode!r}",
            ) from e

    started = time.perf_counter()
    hits, matched_via = _retrieve(req, alias_repo, course_repo, hybrid)
    retrieval_ms = (time.perf_counter() - started) * 1000

    log.info(
        "chat.retrieved",
        query=req.query,
        matched_via=matched_via,
        count=len(hits),
        retrieval_ms=round(retrieval_ms, 2),
    )

    prompt = build_prompt(req.query, hits)

    def event_stream() -> Iterator[bytes]:
        # Meta first so the client can render evidence bubbles before LLM
        # tokens land.
        meta_payload: dict[str, Any] = {
            "type": "meta",
            "matched_via": matched_via,
            "retrieval_ms": round(retrieval_ms, 2),
            "results": [
                {
                    "course_id": h.course.course_id,
                    "primary_code": h.course.primary_code,
                    "primary_name": h.course.primary_name,
                    "score": float(h.score),
                }
                for h in hits
            ],
        }
        yield (json.dumps(meta_payload) + "\n").encode("utf-8")

        try:
            for chunk in stream_fn(prompt):
                payload = {"type": "token", "text": chunk}
                yield (json.dumps(payload) + "\n").encode("utf-8")
        except GeminiError as e:
            log.warning("chat.stream_failed", error=str(e))
            yield (json.dumps({"type": "error", "detail": str(e)}) + "\n").encode(
                "utf-8"
            )
        except Exception as e:  # defensive — never crash the stream
            log.exception("chat.stream_unhandled")
            yield (
                json.dumps(
                    {"type": "error", "detail": f"{type(e).__name__}: {e}"}
                )
                + "\n"
            ).encode("utf-8")

        yield (json.dumps({"type": "done"}) + "\n").encode("utf-8")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _retrieve(
    req: ChatRequest,
    alias_repo: AliasRepository,
    course_repo: CourseRepository,
    hybrid: HybridRetriever,
) -> tuple[list[SearchHit], str]:
    """Alias-first then HybridRetriever, returning (hits, matched_via)."""
    alias_ids = normalize_query_to_course_ids(req.query, alias_repo=alias_repo)
    if alias_ids:
        out: list[SearchHit] = []
        for cid in alias_ids[: req.k]:
            try:
                course = course_repo.get(cid)
            except LookupError:
                continue
            out.append(SearchHit(course=course, score=1.0))
        if out:
            return out, "alias"

    filters = _hard_filters(req)
    hits = hybrid.search(req.query, hard_filters=filters or None, k=req.k)
    return hits, "hybrid" if hits else "empty"


def _hard_filters(req: ChatRequest) -> dict[str, object]:
    out: dict[str, object] = {}
    if req.term is not None:
        out["term"] = req.term
    if req.credits is not None:
        out["credits"] = req.credits
    if req.delivery_mode is not None:
        out["delivery_mode"] = req.delivery_mode
    if req.professor is not None:
        out["professor"] = req.professor
    return out
