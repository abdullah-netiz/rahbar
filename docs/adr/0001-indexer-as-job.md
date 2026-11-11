# ADR 0001: The Indexer as an Independent Batch Job

## Status
Accepted · 2026-11-03

## Context
In early local prototypes and student architectures, indexing documents on API application startup is common practice. However, running indexing inside the API process on Kubernetes introduces severe architectural failure modes:
1. **Multi-Replica Race Conditions**: With the API configured for horizontal scalability (3+ replicas) sharing a single PersistentVolumeClaim mounted to the Chroma vector store, three pods starting concurrently race to extract, chunk, and embed documents simultaneously. This causes concurrent write conflicts, index corruption, and duplicate chunk IDs.
2. **Restart Amplification & Cluster Storms**: If an API container restarts due to a rolling deployment, node drain, liveness blip, or OOM event, it would re-extract and re-embed the entire corpus from scratch. This wastes compute and exhausts LLM/embedding rate limits.
3. **Readiness Probe Corruption**: If the API waits to complete indexing before reporting ready, container startup takes several minutes, tripping Kubernetes `startupProbe` / `readinessProbe` timeouts and triggering restart loops. Conversely, if it reports ready before indexing completes, it serves empty retrievals and hallucinated answers to live end-users.
4. **Coupled Deployment Lifecycle**: Re-indexing when policies update would require releasing a new API image version or redeploying the serving layer, violating separation of concerns and causing unnecessary query downtime.

## Decision
We decouple the indexing pipeline entirely from the query serving path by implementing the Indexer as an independent Kubernetes `Job` (`indexer-job.yaml`) and recurring scheduled `CronJob` (`reindex-cronjob.yaml`).

Under this model:
- **Single Writer Principle**: Only the indexer Job holds write permissions to the Chroma collection.
- **Read-Only API**: The FastAPI API deployment acts strictly as a reader.
- **Gated Readiness**: The API's `/readyz` probe validates that the Chroma vector store is reachable, the collection exists, contains chunks, and matches the pinned `EMBED_MODEL`. If indexing has not completed, the API withholding itself from traffic until the index is non-empty.
- **On-Demand Re-Indexing**: Whenever policies change, re-indexing is triggered via:
  ```bash
  kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar
  ```
  The API continues serving existing queries without restart or downtime.

## Options Considered
1. **API Startup Hook (`@app.on_event('startup')`)**: Rejected. Suffers from the 3-pod write race condition, repeated compute waste on rolling updates, and readiness lies.
2. **Kubernetes `initContainers` on API Pods**: Rejected. Although `initContainers` run before application containers, each replica pod still runs its own `initContainer`, leading to duplicate indexing runs and races across replicas.
3. **Dedicated Indexer Kubernetes Job + Weekly CronJob**: Selected. Guarantees exactly-one writer, zero duplicate indexing on pod restarts, zero-downtime re-indexing, and clean resource isolation (batch memory limits separate from serving limits).

## Consequences
- **Positive**: Eliminates write concurrency races on Chroma; isolates memory spikes (OCR and large document parsing) inside an ephemeral batch pod; enables independent scaling and resource limits; re-indexing requires no code redeployment.
- **Negative / Watch Items**: When re-indexing completes with updated documents, the API's semantic cache must be invalidated so that stale cached answers are not served. We handle this via cache generation tags and invalidation hooks.

