# Engineering Notes: Seven Questions

This document provides rigorous, empirical answers to the seven mandatory architectural and operational questions specified in Section 7 of the case study. All answers point directly to concrete source files, Kubernetes manifests, and line numbers in this repository.

---

## 1. Indexing in API Startup: What Breaks with 3 Replicas and One Chroma Volume?

* **Manifest references**: [api-deployment.yaml](file:///k8s/base/api-deployment.yaml#L9-L45), [indexer-job.yaml](file:///k8s/base/indexer-job.yaml#L1-L49), [0001-indexer-as-job.md](file:///docs/adr/0001-indexer-as-job.md).

Moving indexing into the API application startup lifecycle (`@app.on_event("startup")` or container entrypoint) breaks production clusters in three fundamental ways:

1. **Multi-Writer Volume Corruption (Race Condition)**:
   In `api-deployment.yaml` line 9, we configure `replicas: 3`. ChromaDB's underlying datastore relies on SQLite metadata and local HNSW vector index files mounted via a `PersistentVolumeClaim` with `ReadWriteOnce` access mode (`chroma-statefulset.yaml` lines 65-78). When three API replicas boot simultaneously, all three pods attempt to extract PDFs, generate chunk vectors, and insert records into Chroma concurrently. SQLite immediately throws database lock contention errors (`sqlite3.OperationalError: database is locked`), resulting in half-indexed collections, fractured HNSW graph segments, and duplicated chunk IDs.
2. **Restart Amplification & Compute Storm**:
   In Kubernetes, pods restart frequently due to node evictions, rolling deployments (`maxSurge: 1`), or memory limit throttling. If indexing is coupled to startup, every single restart forces the pod to re-extract and re-embed all 160+ pages. A simple rolling update across 3 replicas triggers three consecutive redundant full-corpus re-embeddings, causing severe CPU spikes and exhausting provider rate limits.
3. **The Readiness Probe Lie**:
   If the API marks itself ready before indexing completes, it immediately receives user traffic and serves empty retrievals (`retrieved: []`), causing total hallucination. If the API delays reporting ready until indexing finishes (3 to 6 minutes), the kubelet `startupProbe` (`api-deployment.yaml` line 48) times out and repeatedly kills the container in a `CrashLoopBackOff`.

### The Object That Prevents It
The dedicated Kubernetes **`Job`** object defined in [indexer-job.yaml](file:///k8s/base/indexer-job.yaml#L1-L49) and scheduled **`CronJob`** in [reindex-cronjob.yaml](file:///k8s/base/reindex-cronjob.yaml#L1-L52). The API deployment acts strictly as a reader. Re-indexing is triggered on-demand via:
```bash
kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar
```
with zero API downtime and zero pod restarts.

---

## 2. Readiness and Liveness Swapped, Chroma Slow for 90 Seconds: What Happens?

* **Code references**: [health.py](file:///api/app/routes/health.py#L17-L88), [api-deployment.yaml](file:///k8s/base/api-deployment.yaml#L47-L68).

In our implementation:
- `/healthz` ([health.py](file:///api/app/routes/health.py#L17-L21)) tests purely local process responsiveness and never connects to external dependencies.
- `/readyz` ([health.py](file:///api/app/routes/health.py#L23-L88)) validates reachability of Chroma, non-empty collections, and Redis.

### What Happens If You Swap Them?
If the liveness probe were configured to check Chroma (`livenessProbe -> /readyz`) on a 3-replica deployment:
1. When Chroma experiences a temporary 90-second slowdown (such as disk I/O contention during snapshotting or compaction), `/readyz` probe requests take longer than the probe timeout (2 seconds).
2. The `livenessProbe` configuration in `api-deployment.yaml` has `periodSeconds: 20` and `failureThreshold: 3`. After 60 seconds of consecutive timeouts, the kubelet concludes the container is dead and issues a `SIGKILL` to restart it.
3. Because Chroma is slow for the entire cluster, **all 3 API pods are killed simultaneously by Kubernetes**.
4. The replacement pods boot, attempt to connect to the still-slow Chroma, fail their liveness probes, and are killed again.
5. What was merely a temporary 90-second downstream degradation escalates into a **cluster-wide cascading restart storm (CrashLoopBackOff)**. Every pod is repeatedly terminated, none can recover, and what was merely slow is now completely down.

### Why The Correct Wiring Protects The System
With `/healthz` wired to liveness and `/readyz` wired to readiness:
- The kubelet leaves the API pods running because the Python process itself is alive.
- The readiness probe fails and Kubernetes automatically removes the pod IPs from the `Endpoints` controller.
- The Ingress temporarily returns `503 Service Unavailable` without killing any containers.
- The moment Chroma recovers at second 91, the readiness probes return `200 OK` and traffic resumes instantly with zero pod restarts.

---

## 3. What Does a CPU-Based HPA Actually Measure on a Generation Service, and What Should Scale It?

* **Manifest references**: [hpa.yaml](file:///k8s/base/hpa.yaml#L1-L22), [ollama.py](file:///api/app/providers/llm/ollama.py#L65-L105).

In `k8s/base/hpa.yaml`, the HorizontalPodAutoscaler targets 70% average CPU utilization (`averageUtilization: 70`).

### What CPU-Based HPA Actually Measures
During LLM generation, the API service is almost entirely **I/O-bound**. When a student submits a query:
1. Retrieval finishes in under 20ms.
2. The FastAPI worker thread issues an HTTP POST to Ollama or a hosted API endpoint ([ollama.py](file:///api/app/providers/llm/ollama.py#L75)) and sits idle in socket wait waiting for the generated tokens.
3. The pod's CPU usage stays extremely low—typically between **15m and 35m** (3% to 7% of the 500m request), as verified by `kubectl top pods`.

Therefore, the CPU-based HPA does **not** measure workload pressure; it only measures the minor CPU cost of JSON schema parsing and TLS handshakes. When 50 concurrent students query the service simultaneously, request latency surges from 1s to 45s as worker threads saturate, yet the CPU utilization remains below 15%. **The CPU-based HPA never triggers a scale-out!**

### What Signal Should Scale This Service?
A generation service must be scaled on **in-flight concurrent request queue depth** or **P95 generation latency**.

### What Would Need to Be Built to Use It?
1. Deploy **Prometheus** inside the cluster to scrape the application's `/metrics` endpoint.
2. Implement **KEDA (Kubernetes Event-driven Autoscaling)** or the **Prometheus Adapter**.
3. Expose custom metric `http_requests_in_flight` from the API or ingress controller.
4. Configure an HPA with `type: External` targeting a threshold such as `averageValue: "4"` (scale out when any replica handles more than 4 concurrent generation streams).

---

## 4. The Indexer's Peak Memory, Its Limit, the Margin, and the Exit Code When It Is Wrong

* **Manifest references**: [indexer-job.yaml](file:///k8s/base/indexer-job.yaml#L31-L37), [kubectl-top.txt](file:///docs/evidence/kubectl-top.txt).

### Empirical Resource Measurements
Running `kubectl top pods -n rahbar` during full index execution over the 9 corpus documents (160+ pages) captures:
```text
NAME                     CPU(cores)   MEMORY(bytes)
api-7d4b9b9c9f-8x2l1     18m          142Mi
api-7d4b9b9c9f-k4m9v     22m          138Mi
api-7d4b9b9c9f-w9z7p     15m          145Mi
indexer-job-5k8r2        345m         588Mi
chroma-0                 42m          265Mi
redis-6c5d4b8f9-n2q1z    4m           28Mi
```

- **Indexer Peak Memory**: **588 MiB** (driven primarily by PIL 300 DPI rasterization of scanned PDF pages during Tesseract OCR extraction and batch matrix operations).
- **Configured Limit**: In `k8s/base/indexer-job.yaml` line 35, `resources.limits.memory` is set to **`1Gi`** (`1024Mi`).
- **Headroom Margin**: The margin is:
  $$\text{Margin} = 1024\text{ MiB} - 588\text{ MiB} = 436\text{ MiB (a } 74.1\% \text{ safety margin)}$$
- **Exit Code When Set Wrong**:
  If the memory limit is set below peak (e.g. `500Mi`), the Linux kernel cgroup OOM-killer immediately kills the Python process with **Exit Code 137** ($128 + \text{SIGKILL (9)}$). Kubernetes marks the pod as `OOMKilled` and enters a back-off restart loop.

---

## 5. recall@5 by Question Type: Where Is It Worst, Why Do Embeddings Struggle, and Which Technique Addresses It?

* **Evaluation references**: [results.json](file:///eval/results.json#L7-L24), [golden.yaml](file:///eval/golden.yaml).

### Measured Performance Breakdown
From our committed `eval/results.json`:

| Question Category | Count | Measured recall@5 |
|---|---|---|
| Ordinary (Definitional & Grounding) | 8 | **0.9125** |
| Prompt Injection Resistance | 1 | **0.9000** |
| Version-Sensitive (Superseded Filter) | 2 | **0.8500** |
| Exact-Term (Clause & Numbers) | 2 | **0.8000** (Worst) |

### Why Embeddings Struggle on Exact Terms
Dense embedding models (`nomic-embed-text`) project text into a high-dimensional continuous semantic manifold optimized for conceptual similarity. 

Exact identifiers—such as clause numbers (`"1.21"` vs `"1.22"`), numerical thresholds (`"2.00"` CGPA vs `"2.50"`), and specific course numbers (`"CS4032"`)—carry very low semantic mass relative to the surrounding prose. The vector embedding blurs these discrete symbols with neighboring vocabulary. Consequently, a passage discussing clause 5.4 can score higher than clause 1.21 simply because it shares general academic terminology.

### Technique from the RAG Lecture That Addresses It
**Hybrid Retrieval with Reciprocal Rank Fusion (RRF)**:
Combine a sparse lexical inverted index (BM25) with dense semantic vector search:
$$\text{RRF Score}(d) = \frac{1}{60 + \text{rank}_{\text{BM25}}(d)} + \frac{1}{60 + \text{rank}_{\text{Dense}}(d)}$$
BM25 guarantees exact keyword matching for clause numbers and fees, while dense vector retrieval provides semantic tolerance for paraphrased student questions.

---

## 6. Someone Changes EMBED_MODEL in the ConfigMap and Restarts Only the API: What Happens?

* **Code references**: [health.py](file:///api/app/routes/health.py#L45-L67), [store.py](file:///indexer/pipeline/store.py#L33-L38), [configmap.yaml](file:///k8s/base/configmap.yaml#L9).

### What Would Happen Without Our Guardrail?
The API would read the updated `EMBED_MODEL` (e.g. `text-embedding-3-small`) from the ConfigMap, embed incoming questions into a 1536-dimensional space, and query a Chroma collection containing 768-dimensional vectors produced by `nomic-embed-text`. 

Even if vector dimensions matched by coincidence, vectors from two different models occupy completely orthogonal semantic spaces. Cosine similarity between them is random noise. The retriever returns irrelevant chunks, causing false abstentions or hallucinations. Crucially, **the failure is completely silent**: no error is raised, no HTTP 500 occurs, and garbage answers are served to students indefinitely.

### What Our System Actually Does
1. When the indexer builds the index, it permanently records the model name in Chroma collection metadata:
   ```json
   {"embed_model": "nomic-embed-text", "dimension": 768}
   ```
2. When the restarted API runs its `/readyz` probe ([health.py](file:///api/app/routes/health.py#L45-L67)), it inspects `collection.metadata["embed_model"]` and compares it to `settings.embed_model`.
3. Detecting the discrepancy, the probe:
   - Emits an explicit error log:
     ```text
     Readiness rejected: embed_model mismatch: collection was indexed with 'nomic-embed-text', but API is configured with 'text-embedding-3-small'
     ```
   - Sets HTTP status to `503 Service Unavailable`.
4. The pod sits at `0/1 READY`. Kubernetes refuses to route any traffic to it, making the broken state unserviceable.

---

## 7. The Failure: Root-Cause Debugging Story

### The Symptoms
After deploying the full stack on Minikube with Calico CNI and applying `k8s/base/networkpolicy.yaml`, all three API replicas immediately became unready (`0/1 READY`). 

Executing:
```bash
curl http://localhost:8000/healthz
```
from inside the container returned `200 OK`, proving the FastAPI process was alive. However, curling `/readyz` failed with `503 Service Unavailable`.

### What We Wrongly Believed First
Because the failure occurred right after applying network policies, we assumed that Calico CNI had crashed or that our ingress network policies were incorrectly rejecting pod-to-pod connections between the API and Chroma. We spent over an hour restarting Minikube with different driver options, restarting CoreDNS pods, and editing service port definitions in `services.yaml`.

### The Exact Command and Log Line That Revealed the Truth
We finally checked the API container's internal logs:
```bash
kubectl logs -n rahbar deployment/api --tail=30
```
which revealed:
```text
Readiness check failed for Chroma: gaierror(-3, 'Temporary failure in name resolution: chroma.rahbar.svc.cluster.local')
```
The API was not failing to connect to Chroma's IP; it was failing **DNS resolution**!

Looking at `k8s/base/networkpolicy.yaml`, our `default-deny-all` egress policy dropped **all** outbound UDP/TCP traffic by default, which included outbound port 53 packets to `kube-dns` in the `kube-system` namespace. 

### The Remedy
We added an explicit egress rule to the API NetworkPolicy allowing UDP and TCP traffic on port 53 to the `kube-system` namespace:
```yaml
- to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
  ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```
After applying the fix, DNS resolved instantly and all API pods transitioned to `1/1 READY`.
