"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

from typing import Any

from .config import IndexerSettings
from .models import Chunk


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count.
    """
    if not chunks:
        return 0

    client = get_client(settings)
    dimension = len(vectors[0]) if vectors and len(vectors) > 0 else 768

    # Store the EMBED_MODEL pin and dimension in collection metadata for API verification (section 4.4)
    collection_metadata = {
        "embed_model": settings.embed_model,
        "embedding_model": settings.embed_model,
        "dimension": dimension,
        "description": "RAHBAR indexed document corpus",
    }

    # Delete existing collection if any to perform a clean atomic re-index (ADR 0001)
    try:
        client.delete_collection(name=settings.collection)
    except Exception:
        pass

    collection = client.create_collection(
        name=settings.collection,
        metadata=collection_metadata,
    )

    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_vectors = vectors[i : i + batch_size]

        ids = [c.id for c in batch_chunks]
        documents = [c.text for c in batch_chunks]
        metadatas = [
            {
                "source": c.source,
                "section": c.section,
                "page": c.page,
                "doc_version": c.doc_version,
                "superseded": c.superseded,
            }
            for c in batch_chunks
        ]

        collection.upsert(
            ids=ids,
            embeddings=batch_vectors,
            documents=documents,
            metadatas=metadatas,
        )

    return len(chunks)
