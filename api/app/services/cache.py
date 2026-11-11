"""Semantic cache over Redis with cosine similarity matching (section 3.3).

Caches query embeddings and grounded answers. Implements strict never-cache rules
(never cache follow-ups, abstentions, out-of-scope answers, or fallbacks) and
invalidation on re-index.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from ..config import Settings
from ..routes.metrics import CACHE_HITS, CACHE_MISSES
from ..schemas import AskResponse

log = logging.getLogger("rahbar.cache")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two normalized vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class SemanticCache:
    """Persistent Redis semantic cache layer with cosine similarity matching."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis_client: Any = None
        self._memory_cache: dict[str, dict[str, Any]] = {}  # fallback if redis offline

    def _get_client(self) -> Any:
        if self._redis_client is None:
            try:
                import redis

                self._redis_client = redis.Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                    decode_responses=True,
                )
                self._redis_client.ping()
            except Exception as exc:
                log.debug("Redis connection not available; using in-memory cache fallback: %s", exc)
                self._redis_client = None
        return self._redis_client

    def _generation_key(self) -> str:
        """Cache generation key; bumped on re-index to invalidate stale entries."""
        client = self._get_client()
        if client:
            try:
                gen = client.get("rahbar:cache:generation_id")
                if not gen:
                    client.set("rahbar:cache:generation_id", "1")
                    return "1"
                return str(gen)
            except Exception:
                pass
        return "1"

    def invalidate(self) -> None:
        """Invalidate the cache by bumping generation_id and expiring old entries.

        Called when the indexer Job finishes a re-index.
        """
        log.info("Invalidating semantic cache on re-index")
        client = self._get_client()
        if client:
            try:
                client.incr("rahbar:cache:generation_id")
                # Also flush db keys matching cache namespace
                keys = client.keys("rahbar:cache:entry:*")
                if keys:
                    client.delete(*keys)
            except Exception as exc:
                log.warning("Failed to invalidate Redis cache: %s", exc)
        self._memory_cache.clear()

    def flush_cache(self) -> None:
        """Alias for invalidate (section 3.3)."""
        self.invalidate()

    def get(
        self,
        question: str,
        question_vector: list[float],
        is_followup: bool = False,
    ) -> tuple[AskResponse | None, float | None]:
        """Look up semantic cache by vector cosine similarity.

        Returns (AskResponse, score) on hit, or (None, None) on miss.
        """
        # Never-cache rule: never cache or check cache for follow-up questions
        if is_followup:
            log.debug("Skipping cache: is_followup=True (never-cache rule)")
            return None, None

        if not self.settings.cache_enabled:
            return None, None

        client = self._get_client()
        threshold = self.settings.cache_threshold
        gen_id = self._generation_key()

        best_score = 0.0
        best_payload: dict[str, Any] | None = None

        if client:
            try:
                keys = client.keys(f"rahbar:cache:entry:{gen_id}:*")
                for key in keys:
                    raw = client.get(key)
                    if not raw:
                        continue
                    entry = json.loads(raw)
                    cached_vec = entry.get("vector")
                    if cached_vec and len(cached_vec) == len(question_vector):
                        sim = cosine_similarity(question_vector, cached_vec)
                        if sim > best_score:
                            best_score = sim
                            best_payload = entry.get("response")
            except Exception as exc:
                log.warning("Redis cache read error: %s", exc)

        # Check in-memory fallback if not found in Redis
        if best_payload is None:
            for k, entry in self._memory_cache.items():
                if not k.startswith(f"gen:{gen_id}:"):
                    continue
                cached_vec = entry.get("vector")
                if cached_vec and len(cached_vec) == len(question_vector):
                    sim = cosine_similarity(question_vector, cached_vec)
                    if sim > best_score:
                        best_score = sim
                        best_payload = entry.get("response")

        if best_score >= threshold and best_payload is not None:
            CACHE_HITS.inc()
            log.info("Semantic cache HIT (similarity=%.4f >= threshold=%.2f)", best_score, threshold)
            cached_resp = AskResponse.model_validate(best_payload)
            return cached_resp, best_score

        CACHE_MISSES.inc()
        log.debug("Semantic cache MISS (best_score=%.4f < threshold=%.2f)", best_score, threshold)
        return None, None

    def set(
        self,
        question: str,
        question_vector: list[float],
        response: AskResponse,
        is_followup: bool = False,
        was_fallback: bool = False,
    ) -> bool:
        """Store response in cache if it passes all never-cache rules."""
        # Never-cache rules (section 3.3):
        # 1. Never cache follow-up questions
        # 2. Never cache abstentions (answered_from_context is False)
        # 3. Never cache validation fallbacks
        # 4. Never cache out-of-scope answers
        if not self.settings.cache_enabled:
            return False
        if is_followup:
            log.debug("never_cache: follow-up question skipped")
            return False
        if not response.answered_from_context:
            log.debug("never_cache: abstention skipped (answered_from_context=False)")
            return False
        if was_fallback:
            log.debug("never_cache: fallback answer skipped")
            return False

        gen_id = self._generation_key()
        entry_id = f"{gen_id}:{abs(hash(question))}"
        payload = {
            "question": question,
            "vector": question_vector,
            "response": response.model_dump(),
        }

        client = self._get_client()
        stored = False
        if client:
            try:
                key = f"rahbar:cache:entry:{entry_id}"
                client.setex(key, self.settings.cache_ttl, json.dumps(payload))
                stored = True
            except Exception as exc:
                log.warning("Failed to store entry in Redis: %s", exc)

        # Store in-memory cache as well
        self._memory_cache[f"gen:{entry_id}"] = payload
        return stored
