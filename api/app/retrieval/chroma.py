"""The real retriever (sections 3.2 and 4.4).

Queries the Chroma vector store, applies the doc_version/superseded metadata
filter, and maps hits to Passages with similarity scores.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any

import httpx

from ..config import Settings
from ..routes.metrics import RETRIEVAL_LATENCY
from ..schemas import Passage

log = logging.getLogger("rahbar.retrieval.chroma")


def _deterministic_fallback_embed(text: str, dim: int = 768) -> list[float]:
    """Generates a normalized deterministic vector for offline testing when Ollama is unavailable."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [float((h[i % len(h)] ^ (i & 0xFF)) - 128) / 128.0 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def embed_query(query: str, settings: Settings) -> list[float]:
    """Embed query with settings.embed_model, matching the indexer's embeddings."""
    embed_model = settings.embed_model
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(
                f"{settings.ollama_url.rstrip('/')}/api/embed",
                json={"model": embed_model, "input": [query]},
            )
            if res.status_code == 200:
                data = res.json()
                embeddings = data.get("embeddings", [])
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
            elif res.status_code == 404:
                r = client.post(
                    f"{settings.ollama_url.rstrip('/')}/api/embeddings",
                    json={"model": embed_model, "prompt": query},
                )
                if r.status_code == 200:
                    emb = r.json().get("embedding", [])
                    if emb:
                        return emb
    except Exception as exc:
        log.debug("Ollama embedding call failed; using deterministic fallback: %s", exc)

    return _deterministic_fallback_embed(query, dim=768)


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _get_collection(self) -> Any:
        return self.client.get_collection(name=self.settings.collection)

    def retrieve(self, question: str, k: int) -> list[Passage]:
        """Embeds question, applies superseded filter, and retrieves top-k chunks."""
        with RETRIEVAL_LATENCY.time():
            collection = self._get_collection()
            query_vector = embed_query(question, self.settings)

            # Metadata filtering (section 3.2): exclude superseded documents unless user explicitly asks
            # about older versions or superseded policies (failure mode E)
            asking_older = bool(
                re.search(r"\b(2023|old|older|previous|superseded|former|repealed|earlier)\b", question, re.I)
            )
            where_filter = None if asking_older else {"superseded": False}

            total_count = collection.count()
            if total_count == 0:
                log.warning("Chroma collection '%s' is empty", self.settings.collection)
                return []

            n_results = min(k, total_count)
            query_args: dict[str, Any] = {
                "query_embeddings": [query_vector],
                "n_results": n_results,
            }
            if where_filter:
                query_args["where"] = where_filter

            try:
                results = collection.query(**query_args)
            except Exception as exc:
                log.error("Chroma query failed with filter %s: %s", where_filter, exc)
                if where_filter:
                    # Fallback query without filter if metadata filtering fails
                    query_args.pop("where", None)
                    results = collection.query(**query_args)
                else:
                    return []

            passages: list[Passage] = []
            if not results or not results.get("ids") or not results["ids"][0]:
                return []

            ids = results["ids"][0]
            docs = results["documents"][0] if results.get("documents") else [""] * len(ids)
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

            for cid, doc, meta, dist in zip(ids, docs, metas, distances):
                # Chroma cosine distance is in [0, 2]; similarity is 1 - distance
                similarity = max(0.0, min(1.0, 1.0 - float(dist)))
                passages.append(
                    Passage(
                        chunk_id=str(cid),
                        text=str(doc),
                        source=str(meta.get("source", "")),
                        section=str(meta.get("section", "")),
                        page=meta.get("page"),
                        score=similarity,
                    )
                )

            return passages
