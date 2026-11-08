# ADR 0003: Semantic Cache Storage Engine (Redis vs Secondary Chroma Collection)

## Status
Accepted · 2026-11-08

## Context
A production RAG question-answering service frequently encounters semantically identical or near-duplicate user queries (e.g. *"What CGPA for probation?"* vs *"What minimum CGPA avoids academic warning?"*). Running the full query pipeline (dense vector embedding, Chroma similarity retrieval, augmented prompt assembly, and LLM text generation) for every question imposes considerable latency ($>1.5\text{s}$ on CPU/local models) and wastes compute.

To achieve sub-$20\text{ms}$ responses for repeated questions, a **semantic caching layer** is required. We evaluated two architectures for storing query vectors and grounded answers:
1. A secondary Chroma collection (`rahbar-cache`).
2. A persistent in-memory Redis datastore (`Deployment + PVC`).

## Decision
We selected **Redis with persistent volume storage (PVC)** as the semantic cache storage engine.

### Implementation Details:
- **Vector Cosine Matching**: Query vectors generated with the pinned `EMBED_MODEL` are compared against cached query vectors using cosine similarity:
  $$\text{similarity} = \frac{\mathbf{q} \cdot \mathbf{c}}{\|\mathbf{q}\| \|\mathbf{c}\|}$$
- **Configurable Threshold**: Cache hits require $\text{similarity} \ge \text{CACHE\_THRESHOLD}$ (configured as $0.90$ in `ConfigMap`).
- **Atomic Cache Invalidation via Generation Keys**: Whenever the indexer batch Job updates the document corpus, it increments `rahbar:cache:generation_id`. All subsequent cache lookups automatically query under the new generation key, atomically invalidating stale cached answers across all API replicas with zero downtime.
- **Strict Never-Cache Rules**:
  - Follow-up questions are never cached (conversational pronouns cause incorrect reuse).
  - Honest abstentions (`answered_from_context: false`) are never cached (ensuring new index updates can immediately answer previously out-of-scope questions).
  - Validation failures or fallbacks are never cached.

## Options Considered

### Option 1: Secondary Chroma Collection (`rahbar-cache`)
- *Pros*: Uses existing Chroma vector search libraries.
- *Cons*:
  - Lacks native key-value TTL (Time-To-Live) expiration.
  - Chroma collections are on-disk SQLite/DuckDB index structures. Writing cache entries concurrently from 3 API replicas causes write contention and locks on the SQLite datastore.
  - Flushing the cache requires rebuilding the Chroma index or deleting all IDs, which is slow and resource-intensive.
  - Read latency ($20-50\text{ms}$) is noticeably higher than Redis in-memory lookup.

### Option 2: Redis Deployment with PVC (`Selected`)
- *Pros*:
  - Sub-millisecond latency for in-memory reads and writes.
  - Native TTL support (`EXPIRE`, `SETEX`) for automatic entry expiration.
  - Single-threaded event loop easily handles $>50,000$ operations per second with zero lock contention across 3 API replicas.
  - Generation key pattern enables instantaneous $O(1)$ cache invalidation on re-indexing.
  - Persistent volume claim ensures cached answers survive API pod restarts and rolling deployments.
- *Cons*:
  - Requires deploying an additional lightweight container in the Kubernetes cluster.

## Consequences
- **Positive**: Reduces end-to-end query latency for popular questions from $\approx 2.0\text{s}$ down to $<15\text{ms}$; drastically decreases load on the LLM provider; guarantees cache invalidation on index rebuilds; survives pod restarts via persistent volume.
- **Negative / Watch Items**: Requires maintaining a persistent Redis deployment in the `rahbar` namespace with appropriate resource requests and limits.
