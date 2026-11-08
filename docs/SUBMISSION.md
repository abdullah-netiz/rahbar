# RAHBAR Submission Dossier & Compliance Audit

This document consolidates all submission deliverables, verification links, and architectural audits required by **Section 8** of the course assignment manual.

---

## 1. Google Classroom Submission Deliverables

### Item 1: GitHub Repository URL
- **Repository**: [https://github.com/abdullah-netiz/rahbar](https://github.com/abdullah-netiz/rahbar)
- **Primary Development Branch**: `dev`
- **Protected Deployment Branch**: `main` (Branch protection enabled, direct pushes disabled)
- **Active Pull Request**: [PR #1: feat: RAHBAR Grounded RAG on Kubernetes](https://github.com/abdullah-netiz/rahbar/pull/1)
- **Collaborators**:
  - Muhammad Anas (`i243088@isb.nu.edu.pk` / GitHub: [`muhammmadanas10`](https://github.com/muhammmadanas10))
  - Abdullah (`i243164@isb.nu.edu.pk` / GitHub: [`abdullah-netiz`](https://github.com/abdullah-netiz))

### Item 2: CI / CD Workflow Execution Verification
- **GitHub Actions CI Workflow**: [`.github/workflows/ci.yml`](file:///c:/SE/Semester%205/SCD/A2/rahbar/.github/workflows/ci.yml)
  - **Passing CI Run ID**: [`42475406819`](https://github.com/abdullah-netiz/rahbar/actions/runs/42475406819) (100% Green on `dev` across all 6 jobs)
  - **PR Verification Run**: [`42476622665`](https://github.com/abdullah-netiz/rahbar/actions/runs/42476622665) (100% Green on PR #1)
  - **Pipeline Jobs**:
    1. `lint`: Ruff formatting/linting and Mypy static typing passed.
    2. `test`: Pytest with $\ge 60\%$ coverage on `app` package using offline stub providers.
    3. `manifests`: Strict Kubeconform validation against Kubernetes v1.30.0 schemas.
    4. `build`: Multi-container Docker Buildx execution for `api`, `indexer`, and `ui`.
    5. `scan`: Trivy vulnerability filesystem scanner (0 HIGH/CRITICAL unpatched vulnerabilities).
    6. `e2e-eval`: Ephemeral Kind cluster initialization, manifest rollout, indexer Job execution, and golden set eval regression gate.
- **GitHub Actions CD Workflow**: [`.github/workflows/cd.yml`](file:///c:/SE/Semester%205/SCD/A2/rahbar/.github/workflows/cd.yml)
  - Automatically executes on push (or merge) to `main`.
  - Step dependency graph: `test` $\rightarrow$ `build-push` (needs: `test`) $\rightarrow$ `deploy` (needs: `build-push`).
  - Strict commit SHA container image tagging.
  - Ephemeral Kind deployment verification with `kubectl rollout status` and automated Ingress `/healthz` smoke test.

### Item 3: Docker Hub Container Images (Tagged by SHA)
- **Registry**: Docker Hub
- **Images Published**:
  - `abdullahnetiz/rahbar-api:<commit-sha>`
  - `abdullahnetiz/rahbar-indexer:<commit-sha>`
  - `abdullahnetiz/rahbar-ui:<commit-sha>`
- **Deployment Invariant**: All production deployments are referenced strictly by unique git commit SHA (`${{ github.sha }}`), never floating `:latest` tags.

### Item 4: Evaluation Benchmark Artifacts
- **Baseline Metrics File**: [`eval/baseline.json`](file:///c:/SE/Semester%205/SCD/A2/rahbar/eval/baseline.json)
- **Current Results File**: [`eval/results.json`](file:///c:/SE/Semester%205/SCD/A2/rahbar/eval/results.json)
- **Curated Golden Dataset**: [`eval/golden.yaml`](file:///c:/SE/Semester%205/SCD/A2/rahbar/eval/golden.yaml) (15 questions covering ordinary, version-sensitive, exact-term, must-abstain, and prompt injection probes)
- **Benchmark Summary**:
  - $\text{Recall@5} = 0.8718$ (Exceeds baseline threshold)
  - $\text{Citation Validity} = 0.9850 \ge 0.9500$
  - $\text{Abstention Correctness} = 1.0000$ (100% honesty on out-of-domain queries)

---

## 2. Deduction Avoidance & Compliance Matrix

| Rule / Requirement | Required Specification | Implementation Detail | Status |
| :--- | :--- | :--- | :--- |
| **No Plain Secrets in Git** (-20) | Never commit plain credentials or keys. | All API keys ingested at runtime via `LLM_API_KEY` in `rahbar-secret`. Secret files gitignored. | **VERIFIED** |
| **No Real Base64 Secrets** (-15) | Manifests must only contain templates. | [`k8s/base/secret.placeholder.yaml`](file:///c:/SE/Semester%205/SCD/A2/rahbar/k8s/base/secret.placeholder.yaml) is an uncommitted template. | **VERIFIED** |
| **Reader / Writer Split** (-10) | API startup must never index documents. | Chroma writes live exclusively in the `indexer` Job. API runs in read-only mode across 3 replicas. | **VERIFIED** |
| **Citation Grounding** (-10) | Returned citations must match retrieved chunks. | [`api/app/services/answer.py`](file:///c:/SE/Semester%205/SCD/A2/rahbar/api/app/services/answer.py) verifies every citation against retrieved passages. | **VERIFIED** |
| **Honest Abstention** (-10) | Must-abstain questions never answered from context. | Relevance floor ($\text{floor}=0.65$) triggers honest abstention with `answered_from_context: false`. | **VERIFIED** |
| **Stateful PVC Storage** (-8) | Chroma & Redis must use persistent storage without exposing node ports. | Chroma uses `StatefulSet` with `volumeClaimTemplates`; Redis uses PVC. Services are `ClusterIP`. | **VERIFIED** |
| **Embedding Model Pinning** (-8) | Indexer and API must agree on model without silent drift. | Model (`nomic-embed-text`) stored in collection metadata; [`/readyz`](file:///c:/SE/Semester%205/SCD/A2/rahbar/api/app/routes/health.py) returns 503 on mismatch. | **VERIFIED** |
| **Resource Requests & Limits** (-6) | Every container must specify requests and limits. | Requests and limits defined across all manifests; HPA has valid CPU metrics. | **VERIFIED** |
| **Needs Gating in Workflows** (-6) | Publishing and deploying must be gated by tests. | `build-push` has `needs: test`; `deploy` has `needs: build-push`. SHA tags enforced. | **VERIFIED** |
| **Explicit Namespace** (-5) | Never deploy to `default` namespace. | All manifests explicitly bind to `namespace: rahbar`. | **VERIFIED** |
| **Deterministic README Order** (-5) | Step-by-step deploy must work on clean clone. | Documented exact sequential apply order in [`README.md`](file:///c:/SE/Semester%205/SCD/A2/rahbar/README.md). | **VERIFIED** |
| **No Direct Pushes to Main** (-4) | Two-branch model with protected main. | All commits pushed to `dev` or feature branches; PR #1 opened for `dev` $\rightarrow$ `main`. | **VERIFIED** |
| **Authorship Balance** | Each partner must author $\ge 35\%$ of commits. | Muhammad Anas: **38%** (23+ commits); Abdullah: **61%** (37 commits). | **VERIFIED** |

---

## 3. Mechanical Submission Check Output

Running `python scripts/check_submission.py` confirms 0 mechanical errors:

```
RAHBAR submission checker — C:\SE\Semester 5\SCD\A2\rahbar

0 • starter kit           [ok] no STARTER-TODO or NotImplementedError stubs
A • structure             [ok] all required docs, directories, and ADRs present
A • git                   [ok] 60+ commits, 38% Anas, 98% conventional prefixes
B • corpus                [ok] 9 source documents with valid SHA-256 MANIFEST
C • indexer               [ok] structure-aware chunker, OCR, ChromaDB writer
D • api & pin             [ok] /healthz, /readyz, /metrics, guardrail, superseded filter
E • generation            [ok] Answer schema, citations, retry & safe fallback
F • cache                 [ok] Redis semantic cache with cosine similarity & never-cache
G • kubernetes            [ok] StatefulSet PVCs, non-root, HPA, NetworkPolicy, Kustomize
H • evaluation            [ok] 15 golden questions, recall@k, citation validity, gate
I • images & CI/CD        [ok] python:3.12-slim, SHA tagging, Trivy scan, needs: gating
J • docs                  [ok] Troubleshooting matrix, 4 ADRs, engineering notes

166 passed · 1 warning · 0 failures
```
