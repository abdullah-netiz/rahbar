# Failure Analysis: Breaking Six Pipeline Stages on Purpose

This document records the deliberate failure analysis conducted across the six stages of the RAHBAR RAG pipeline (section 5.5). In each experiment, we broke one stage on purpose while holding all other parameters constant, observed the failure symptom, diagnosed it using logs and metrics, and verified the remedy.

> **Key Takeaway from RAG Principles**: Only Stage F is the language model's fault. When an answer is wrong, broken, or hallucinated, always diagnose from Stage A to Stage E first.

---

## 1. Stage A · Extraction: Scanned PDF Indexed Without OCR

- **What we broke**: We disabled the optical character recognition (OCR) fallback path in `indexer/pipeline/extract.py` by skipping `pytesseract` and forcing `pypdf` on `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (Policy 27).
- **Symptom**: 
  - The indexer Job completed without throwing an exception, but indexed 0 chunks for Policy 27.
  - Queries regarding faculty start-up equity or intellectual property sharing returned immediate abstentions (`answered_from_context: false`) despite the document existing in the corpus folder.
- **Diagnosis (as if not caused on purpose)**:
  - Checking indexer chunk logs revealed:
    ```text
    extract: extracted 0 characters from 12 pages of faculty-entrepreneurship-and-technical-start-ups-policy.pdf
    ```
  - Running `pdffonts` against the file showed a completely empty font table, confirming the PDF contains raster image scans with no embedded digital font glyphs.
  - In Chroma, `collection.get(where={"source": "faculty-entrepreneurship-and-technical-start-ups-policy.pdf"})` returned 0 IDs.
- **Remedy**:
  - Re-enabled the character threshold heuristic in `extract.py`: if extracted text has fewer than 30 characters per page, rasterize the PDF page to a 300 DPI PIL image and run `pytesseract.image_to_string()`.

---

## 2. Stage B · Chunking: Fixed-Size 100-Token Chunks with No Overlap

- **What we broke**: Modified `indexer/pipeline/chunk.py` to use a naive sliding window of exactly 100 tokens with 0 token overlap, completely disabling the section heading and paragraph boundary heuristics.
- **Symptom**:
  - On the golden evaluation set, `recall@5` for multi-clause rules (e.g. academic probation and generative AI policies) plummeted from `0.87` down to `0.41`.
  - The model began generating fabricated citations (citation validity dropped to 64%) because parent section headings like `"5.4 Academic Warning"` were severed from the rule bodies.
- **Diagnosis (as if not caused on purpose)**:
  - Inspecting retrieved passages logged in `api/app/services/answer.py`:
    ```json
    {"chunk_ids": ["c-104", "c-105"], "scores": [0.68, 0.65], "sections": ["", ""]}
    ```
  - Chunks started in the middle of sentences and lacked `section` metadata.
  - Storage amplification ratio dropped to 1.02x, but the information fragmentation destroyed the retriever's semantic grounding.
- **Remedy**:
  - Restored hierarchical structure-aware chunking with target size 400 tokens and 50 tokens overlap. Chunks preserve heading clause hierarchies and paragraph integrity.

---

## 3. Stage C · Retrieval: Setting top_k to 1 and EMBED_MODEL Mismatch

- **What we broke**: In `k8s/base/configmap.yaml`, set `TOP_K: "1"` (and tested changing `EMBED_MODEL` to `text-embedding-3-small` on the API only).
- **Symptom**:
  - For questions requiring multi-clause context (e.g. repeating a course after academic warning), answers were incomplete and missed second-order policy requirements.
  - Under the `EMBED_MODEL` mismatch experiment, vectors from two different models populated the query and index. Retrieval returned unrelated chunks with near-zero similarity scores ($<0.15$), triggering false abstentions.
- **Diagnosis (as if not caused on purpose)**:
  - For `TOP_K=1`: Retrieval logs showed only a single chunk retrieved per request (`len(passages) == 1`). Complex queries had `recall@5` artificially capped at 0.20.
  - For `EMBED_MODEL` mismatch: The API's `/readyz` probe immediately reported `503 Service Unavailable` with log:
    ```text
    Readiness rejected: embed_model mismatch: indexed=nomic-embed-text, configured=text-embedding-3-small
    ```
- **Remedy**:
  - Restored `TOP_K: 5` in ConfigMap. The embedding pin guardrail in `health.py` strictly prevents mismatched embedding models from serving traffic.

---

## 4. Stage D · Prompt: Removed Context Grounding Instructions

- **What we broke**: In `api/app/providers/llm/ollama.py`, removed the system prompt instruction *"Answer ONLY using the provided evidence passages; if the evidence is insufficient, abstain by setting answered_from_context to false"*.
- **Symptom**:
  - When asked out-of-scope questions (e.g., hostel allotment rules), the LLM ceased abstaining. It hallucinated fluent policies based on generic Pakistani universities instead of declining.
  - On the golden evaluation set, `abstention_correctness` fell from $100\%$ ($1.0$) to $0\%$, immediately failing the CI gate.
- **Diagnosis (as if not caused on purpose)**:
  - In `eval/results.json`, `abstention_correctness: 0.0` was flagged.
  - Responses had `answered_from_context: true` while `retrieved` chunks were either empty or scored below `RELEVANCE_FLOOR`.
- **Remedy**:
  - Enforced prompt delimiting with strict grounding instructions in `SYSTEM_PROMPT` and reinforced programmatic relevance floor checking in `answer_question()`.

---

## 5. Stage E · Source: Removed the Superseded Filter for Versioned Policies

- **What we broke**: In `api/app/retrieval/chroma.py`, commented out `where={"superseded": False}`, allowing repealed 2023 undergraduate regulations to be retrieved alongside current 2026 rules.
- **Symptom**:
  - When asked *"What are the attendance requirements to sit the final exam?"*, the retriever returned clause 1 from the 2023 regulations and clause 1.21 from the 2026 handbook. The LLM quoted outdated 2023 rules as current policy.
  - On version-sensitive golden questions (`q09`, `q10`), the answer accuracy degraded significantly.
- **Diagnosis (as if not caused on purpose)**:
  - Checking the `retrieved` metadata list in the API JSON log:
    ```json
    {"chunk_id": "c-2023-01", "source": "Academic-Rules-Undergrad-Aug-2023.pdf", "superseded": true}
    ```
  - Chunks with `superseded: true` were actively participating in prompt augmentation.
- **Remedy**:
  - Re-enabled automatic metadata filtering: `where={"superseded": False}` unless the user query explicitly mentions keywords like *"2023"*, *"old"*, *"previous"*, or *"superseded"*.

---

## 6. Stage F · Generation: Temperature Raised to 1.2

- **What we broke**: Set `TEMPERATURE: "1.2"` in `k8s/base/configmap.yaml` and `api/app/config.py`.
- **Symptom**:
  - The model frequently produced corrupted JSON with unclosed brackets, leading to JSON decoding errors and triggering the safe fallback path repeatedly (`rahbar_fallbacks_total` counter surged).
  - Even when valid JSON was produced, answers suffered from creative embellishments and hallucinated clause numbers.
- **Diagnosis (as if not caused on purpose)**:
  - Prometheus metric `rahbar_fallbacks_total` showed a high rate of increments.
  - Application logs reported `ValidationError: Invalid JSON format` from Pydantic parsing.
- **Remedy**:
  - Pinned `TEMPERATURE` to $0.2$ in `ConfigMap` and added justifications that factual, schema-constrained generation requires low temperature ($0.0 - 0.3$).
