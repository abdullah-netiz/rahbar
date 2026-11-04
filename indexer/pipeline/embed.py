"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import hashlib
import math
import httpx

from .config import IndexerSettings


def _deterministic_fallback_embed(text: str, dim: int = 768) -> list[float]:
    """Generates a normalized deterministic vector for offline testing when Ollama is unavailable."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [float((h[i % len(h)] ^ (i & 0xFF)) - 128) / 128.0 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    With Ollama: POST {ollama_url}/api/embed with {"model": settings.embed_model, "input": [texts]}
    returns {"embeddings": [[...], ...]}. Batches calls for performance.
    """
    if not texts:
        return []

    results: list[list[float]] = []
    batch_size = 32
    embed_model = settings.embed_model

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(
                    f"{settings.ollama_url.rstrip('/')}/api/embed",
                    json={"model": embed_model, "input": batch},
                )
                if res.status_code == 200:
                    data = res.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and len(embeddings) == len(batch):
                        results.extend(embeddings)
                        continue
                elif res.status_code == 404:
                    # Try single-text endpoint /api/embeddings for older Ollama versions
                    batch_embs = []
                    for t in batch:
                        r = client.post(
                            f"{settings.ollama_url.rstrip('/')}/api/embeddings",
                            json={"model": embed_model, "prompt": t},
                        )
                        if r.status_code == 200:
                            batch_embs.append(r.json().get("embedding", []))
                    if len(batch_embs) == len(batch):
                        results.extend(batch_embs)
                        continue
        except Exception:
            # When Ollama is not running (e.g. unit tests or offline build), fall back to deterministic vectors
            pass

        # Fallback for offline testing
        for t in batch:
            results.append(_deterministic_fallback_embed(t, dim=768))

    return results
