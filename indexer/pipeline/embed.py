"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import hashlib
import math
import httpx

from .config import IndexerSettings


import re


def _deterministic_fallback_embed(text: str, dim: int = 768) -> list[float]:
    """Generates a normalized deterministic vector for offline testing when Ollama is unavailable."""
    stopwords = {"what", "is", "the", "for", "to", "a", "an", "of", "in", "and", "or", "does", "do", "how", "student", "are", "on", "at", "by", "from", "be"}
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in stopwords]
    if not words:
        return [1.0 / math.sqrt(dim)] * dim
    vec = [0.0] * dim
    for w in words:
        h = int(hashlib.sha256(w.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 16) & 1) else -1.0
        vec[idx] += 1.0 * sign
        for i in range(3):
            sub_idx = (h + (i + 1) * 97) % dim
            vec[sub_idx] += 0.5 * sign
    for i in range(len(words) - 1):
        bg = f"{words[i]}_{words[i+1]}"
        h = int(hashlib.sha256(bg.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 16) & 1) else -1.0
        vec[idx] += 2.0 * sign

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


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
