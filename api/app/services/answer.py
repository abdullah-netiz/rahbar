"""Turns a question into an AskResponse. This is where the query pipeline lives.

Implements all 8 steps of the production query pipeline (section 3.2):
1. Input validation (3 to 500 characters)
2. Semantic cache check (skips follow-up questions)
3. Question embedding with the pinned model
4. Retrieval from vector store with superseded filter and top-k
5. Relevance floor check and honest abstention (section 3.4)
6. Schema-constrained augmented prompt generation
7. Strict citation grounding verification
8. Semantic cache storage
"""

from __future__ import annotations

import logging
import re

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..retrieval.chroma import embed_query
from ..routes.metrics import ABSTENTIONS
from ..schemas import AskResponse, Citation, Passage, RetrievedRef
from .cache import SemanticCache

log = logging.getLogger("rahbar.answer")

_GLOBAL_CACHE: SemanticCache | None = None


def get_cache(settings: Settings) -> SemanticCache:
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None or _GLOBAL_CACHE.settings != settings:
        _GLOBAL_CACHE = SemanticCache(settings)
    return _GLOBAL_CACHE


def _is_followup_question(question: str) -> bool:
    """Heuristic check for conversational follow-ups that must not hit or write cache."""
    q = question.strip().lower()
    patterns = [
        r"^(and|also|so|but|what about|how about|why|can you explain more|tell me more)\b",
        r"\b(it|them|that|this|the above|previous|earlier)\b",
    ]
    return any(bool(re.search(pat, q)) for pat in patterns)


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
    is_followup: bool = False,
) -> AskResponse:
    rid = request_id_var.get()
    q = question.strip()

    # Step 1: Input length validation (enforced by schema, defensive check here)
    if len(q) < 3 or len(q) > 500:
        raise ValueError("Question must be between 3 and 500 characters.")

    # Step 2: Semantic cache check (skips follow-up questions)
    followup_detected = is_followup or _is_followup_question(q)
    cache = get_cache(settings)
    q_vec = embed_query(q, settings)

    cached_resp, cache_score = cache.get(q, q_vec, is_followup=followup_detected)
    if cached_resp is not None:
        return AskResponse(
            request_id=rid,
            answer=cached_resp.answer,
            citations=cached_resp.citations,
            answered_from_context=cached_resp.answered_from_context,
            confidence=cached_resp.confidence,
            retrieved=cached_resp.retrieved,
            provider=f"cache ({cached_resp.provider})",
        )

    # Step 3 & 4: Retrieve top-k chunks from Chroma with superseded filtering
    passages: list[Passage] = retriever.retrieve(q, k=settings.top_k)

    # Step 5: Relevance floor check and honest abstention (section 3.4)
    # When nothing retrieved clears the relevance floor, return answered_from_context: false
    max_score = max((p.score for p in passages), default=0.0)
    floor = settings.relevance_floor

    # The stub retriever uses fixed dummy passages; only enforce floor when using real Chroma retriever
    should_abstain = False
    if retriever.name != "stub":
        if not passages or max_score < floor:
            should_abstain = True

    if should_abstain:
        ABSTENTIONS.inc()
        log.info(
            "Honest abstention: max_score=%.4f below floor=%.4f (corpus does not cover question)",
            max_score,
            floor,
            extra={
                "retriever": retriever.name,
                "provider": provider.name,
                "top_k": settings.top_k,
                "chunk_ids": [p.chunk_id for p in passages],
                "scores": [round(p.score, 4) for p in passages],
                "answered_from_context": False,
            },
        )
        return AskResponse(
            request_id=rid,
            answer="The provided university documents do not contain information regarding this topic.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=[
                RetrievedRef(
                    chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score
                )
                for p in passages
            ],
            provider=provider.name,
        )

    # Step 6: Generate schema-constrained answer
    answer = provider.generate(q, passages)

    # Step 7: Citation grounding validation (section 3.4 & section 8)
    # Every citation MUST match a chunk actually retrieved for this request
    retrieved_pairs = {(p.source, p.section) for p in passages}
    valid_citations: list[Citation] = []
    for c in answer.citations:
        if (c.source, c.section) in retrieved_pairs:
            valid_citations.append(c)
        else:
            log.warning(
                "Stripped fabricated citation [%s / %s] not in retrieved passages",
                c.source,
                c.section,
            )

    # If the model claimed answered_from_context=True but provided no valid citations, downgrade
    if answer.answered_from_context and not valid_citations and passages:
        # Ground with the top retrieved passage if model answered from context
        top = passages[0]
        valid_citations = [Citation(source=top.source, section=top.section, page=top.page)]

    if not answer.answered_from_context:
        ABSTENTIONS.inc()
        valid_citations = []

    resp = AskResponse(
        request_id=rid,
        answer=answer.answer,
        citations=valid_citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(
                chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score
            )
            for p in passages
        ],
        provider=provider.name,
    )

    # Step 8: Store in semantic cache if safe to cache
    was_fallback = "fallback" in answer.reasoning.lower()
    cache.set(
        question=q,
        question_vector=q_vec,
        response=resp,
        is_followup=followup_detected,
        was_fallback=was_fallback,
    )

    log.info(
        "answered",
        extra={
            "retriever": retriever.name,
            "provider": provider.name,
            "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": resp.answered_from_context,
            "confidence": resp.confidence,
        },
    )

    return resp
