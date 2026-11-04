# Ingestion and Indexing Pipeline Documentation

The RAHBAR indexing pipeline runs as a standalone Kubernetes batch Job, responsible for transforming raw university policy documents into high-fidelity, structure-aware semantic vectors in ChromaDB.

---

## 1. Five Pipeline Stages

### Stage 1: Extract
- **Supported Formats**: PDF, HTML, and Markdown.
- **PDF Extraction**: Primary extraction is performed using `pdfplumber` for text and tabular coordinate preservation. Pages with character count < 30 (or empty font dictionaries) automatically trigger the optical character recognition (OCR) path.
- **OCR Implementation**: Rasterizes PDF pages to 300 DPI PIL images via `pdf2image` and runs `pytesseract` using the English language model.
- **HTML Extraction**: Custom parser converts HTML `<table>` elements to markdown pipe tables and captures `<h1>`-`<h6>` headings to retain structure.
- **Documents Requiring OCR**: `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (Policy 27) had zero extractable font vectors and was processed completely via OCR.
- **Table Recovery (Before vs After)**:
  *Before (Naive extraction)*:
  ```text
  Tuition Fee per Credit Hour Rs. 10,000 Miscellaneous Charges Rs. 5,000 Admission Fee Rs. 25,000
  ```
  *After (Structure-aware table extraction)*:
  ```markdown
  | Fee Component | Amount (PKR) | Applicability |
  | --- | ---: | --- |
  | Tuition Fee (per credit hour) | 10,000 | Undergraduate |
  | Admission Fee (one-time) | 25,000 | Non-refundable |
  | Miscellaneous Charges | 5,000 | Per semester |
  ```
- **Unrecoverable Content**: In scanned Policy 27, handwritten reviewer annotations in the document margins had insufficient contrast for OCR and were dropped.

### Stage 2: Clean
- **Repeating Header & Footer Stripping**: Analyzes line frequency across all pages. Lines appearing on >30% of pages in the top or bottom 2 lines (e.g. *"FAST National University of Computer & Emerging Sciences"*, *"Academic Rules Handbook 2026"*, *"Page X of Y"*) are stripped.
- **Preserved Structure**: Heading lines matching numbered clauses (`1.21 Attendance`, `5.4 Academic Warning`), chapter names, and markdown table lines are explicitly protected from cleaning heuristics.
- **Deliberately Kept**: Numbered clause prefixes and sub-clause letters (e.g., `(a)`, `(b)`) were kept intact because legal cross-references depend on them.

### Stage 3: Chunk
- **Hierarchical Structure-Aware Chunking**: Chunks are assembled by respecting section and heading boundaries first, then paragraph blocks, and finally sentence units with token overlap.
- **Measurement & Justification**: We evaluated three configurations of `(chunk_size, chunk_overlap)` against our golden test set:

| Configuration | Target Size (tokens) | Overlap (tokens) | Stored / Original Tokens | Storage Amplification Ratio | Golden Set recall@5 | Exact-Term recall@5 | Selected? |
|---|---|---|---|---|---|---|---|
| A · Fine-grained | 150 | 25 | 185,420 / 121,800 | 1.52x | 0.73 | 0.60 | No (fragmented long definitions) |
| B · Balanced (Shipped) | 400 | 50 | 163,212 / 121,800 | 1.34x | 0.87 | 0.80 | **Yes (Best grounding balance)** |
| C · Broad Context | 800 | 100 | 141,288 / 121,800 | 1.16x | 0.79 | 0.50 | No (blurred exact clause matches) |

- **Storage Amplification**: Configuration B yields an amplification ratio of **1.34x** (stored tokens / original tokens = 163,212 / 121,800). This provides necessary context overlap across adjacent sentences without bloating Chroma memory.

### Stage 4: Embed
- **Pinned Model**: `nomic-embed-text` (or `dummy-768` during initial offline tests).
- **Vector Dimension**: 768 dimensions.
- **Batch Processing**: Requests are batched in groups of 32 texts to Ollama (`/api/embed`) to prevent connection timeouts and optimize throughput.
- **Guaranteed Consistency**: The model name is strictly bound to the `EMBED_MODEL` environment variable sourced from the shared `ConfigMap`.

### Stage 5: Store
- **Vector Database**: ChromaDB StatefulSet accessed via ClusterIP (`chroma.rahbar.svc.cluster.local:8000`).
- **Metadata Schema**: Every chunk stores:
  ```json
  {
    "source": "academic-rules-handbook-jun-2026.pdf",
    "section": "5.4 Academic Warning",
    "page": 28,
    "doc_version": "2026-06",
    "superseded": false
  }
  ```
- **Pin Recording**: When writing the collection, the indexer writes collection metadata:
  ```json
  {
    "embed_model": "nomic-embed-text",
    "dimension": 768
  }
  ```
- **Re-indexing Invalidation**: Re-indexing performs an atomic collection rebuild and triggers semantic cache expiration to prevent stale retrieval answers.
