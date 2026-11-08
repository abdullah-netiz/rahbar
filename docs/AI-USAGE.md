# AI Usage Disclosure

In compliance with course policy and Section 8 of the assignment handout, this document details the AI tools used during the design, development, and debugging of RAHBAR, what they generated or shaped, and the manual modifications and verifications we made.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
|---|---|---|
| **Google Antigravity (Gemini 3.8 Flash)** | Initial scaffolding of Kubernetes manifests (`networkpolicy.yaml`, `chroma-statefulset.yaml`, `api-deployment.yaml`) and Dockerfiles. | Manually added `readOnlyRootFilesystem: true`, non-root user IDs, and explicit egress rules for `kube-dns` on port 53 after diagnosing cluster DNS resolution failures under Calico CNI. |
| **Google Antigravity (Gemini 3.8 Flash)** | Hierarchical chunking regex patterns (`chunk.py`) and table markdown parser in extraction stage (`extract.py`). | Refined token counting logic and overlap calculation to restrict storage amplification to 1.34x; added defensive checks for zero-character OCR pages on scanned PDFs. |
| **Google Antigravity (Gemini 3.8 Flash)** | Drafting the 15-question structure in `eval/golden.yaml` across ordinary, version-sensitive, exact-term, abstention, and prompt injection categories. | Verified each question against the real FAST-NUCES June 2026 handbook and Fee Structure pages; manually adjusted clause references (1.21 and 5.4) and expected numerical values. |
| **Google Antigravity (Gemini 3.8 Flash)** | Drafting unit test cases for the API query pipeline (`test_api_pipeline.py`) and evaluation runner (`test_eval_runner.py`). | Fixed mock fixtures to ensure tests remain completely offline with zero live model or external network calls, ensuring fast, deterministic CI execution. |
| **Google Antigravity (Gemini 3.8 Flash)** | Initial drafting of architectural decision records (`0003-semantic-cache-storage.md` and `0004-llm-provider-and-data-governance.md`). | Rewrote technical justifications to point directly to our concrete Kubernetes PVC configuration, generation key invalidation mechanisms, and PII protection policies. |
