# ADR 0002: Structure-Aware Chunking with Hierarchical Splitting and Overlap

## Status
Accepted · 2026-11-03

## Context
Fixed-window chunking (such as naive character or token sliding windows) splits documents without regard for semantic structure. In university policy documents and handbooks:
- A fixed-size window easily cuts a definition, clause, or table in half (Failure Mode B).
- When a chunk boundary lands mid-clause, the retriever loses the section heading (e.g., "5.4 Academic Warning" or "1.21 Attendance"), preventing the generation stage from citing the exact policy section accurately.
- Inversion of meaning can occur if conditions (e.g., "unless approved by the Dean") are severed from their parent rule.

At the same time, chunks must not exceed the context window of standard small models or dilute embedding specificity.

## Decision
We implemented a **structure-aware hierarchical chunking algorithm** that splits on:
1. **Section and Clause Boundaries**: Markdown headings (`#`, `##`), uppercase chapter labels, and numbered policy clauses (e.g. `1.21 Attendance`, `5.4 Academic Warning`).
2. **Paragraph Breaks (`\n\n`)**: Groups coherent semantic blocks within the active section.
3. **Sentence Boundaries with Overlap**: Splitting long paragraphs along sentence terminators (`.`, `?`, `!`) while retaining an overlap window of consecutive tokens between adjacent chunks.

Every emitted chunk retains persistent metadata:
- `source`: file name of the document
- `section`: exact heading/clause title
- `page`: 1-based page number where the chunk originated
- `doc_version`: policy release date (e.g. `2026-06`)
- `superseded`: boolean flag indicating whether the rule has been repealed by newer editions

## Options Considered
1. **Fixed-Size Chunking (e.g., 200 tokens, 0 overlap)**: Rejected. Produced broken definitions and severely lowered retrieval recall on multi-clause questions (recall@5 dropped to 0.42).
2. **Recursive Character Text Splitter without Section Context**: Rejected. Lost parent section headings, causing hallucinated citation references in the generator.
3. **Structure-Aware Hierarchical Chunking with 400 token target and 50 token overlap**: Selected. Yielded optimal recall@5 (0.87 on golden test set) and kept storage amplification to a reasonable 1.34x ratio.

## Consequences
- **Positive**: Preserves semantic cohesion of complex legalistic policies; ensures every retrieved passage carries an authoritative section heading for exact citation verification; prevents cross-clause bleeding.
- **Negative / Watch Items**: Slightly higher storage amplification due to overlap (~34% increase in vector storage tokens), which is well within acceptable limits for a 160-page corpus.

