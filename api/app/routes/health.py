"""Liveness and readiness probes (section 4.3 and 4.4).

Liveness answers: is this container process healthy?
Readiness answers: can this container serve traffic right now?
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response

log = logging.getLogger("rahbar.health")
router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Readiness probe.

    Returns 200 only if Chroma is reachable, the collection is non-empty,
    Redis is reachable, and the collection's embedding model matches EMBED_MODEL.
    Otherwise returns 503 naming the failing dependency.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        response.status_code = 503
        return {"status": "not_ready", "error": "settings not initialized"}

    checks: dict[str, Any] = {}

    # If running in stub mode (offline tests/CI), bypass external datastore checks
    if settings.retriever == "stub" and settings.llm_provider == "stub":
        return {
            "status": "ready",
            "mode": "stub",
            "checks": {"retriever": "stub", "provider": "stub"},
        }

    # 1. ChromaDB reachability and collection non-empty check
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = chroma_client.get_collection(name=settings.collection)
        coll_count = collection.count()

        if coll_count == 0:
            response.status_code = 503
            log.warning("Readiness failed: Chroma collection '%s' is empty (count=0)", settings.collection)
            return {
                "status": "not_ready",
                "dependency": "chroma",
                "error": f"collection '{settings.collection}' is empty; run indexer Job first",
            }
        checks["chroma"] = f"ok ({coll_count} chunks)"

        # 2. Embedding pin guardrail check (section 4.4)
        coll_meta = collection.metadata or {}
        stored_embed_model = coll_meta.get("embed_model") or coll_meta.get("embedding_model")
        if stored_embed_model and stored_embed_model != settings.embed_model:
            log.error(
                "Readiness rejected: embed_model mismatch: collection was indexed with '%s', "
                "but API is configured with '%s'",
                stored_embed_model,
                settings.embed_model,
            )
            response.status_code = 503
            return {
                "status": "not_ready",
                "dependency": "embedding_model",
                "error": (
                    f"embedding_model mismatch: indexed={stored_embed_model}, "
                    f"configured={settings.embed_model}"
                ),
            }
        checks["embed_model"] = f"ok ({settings.embed_model})"

    except Exception as exc:
        log.error("Readiness check failed for Chroma: %s", exc)
        response.status_code = 503
        return {"status": "not_ready", "dependency": "chroma", "error": str(exc)}

    # 3. Redis semantic cache reachability check
    if settings.cache_enabled:
        try:
            import redis

            r = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
            if not r.ping():
                raise ConnectionError("Redis ping failed")
            checks["redis"] = "ok"
        except Exception as exc:
            log.error("Readiness check failed for Redis: %s", exc)
            response.status_code = 503
            return {"status": "not_ready", "dependency": "redis", "error": str(exc)}

    return {"status": "ready", "checks": checks}
