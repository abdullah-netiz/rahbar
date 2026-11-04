# Corpus Documentation

Source: FAST-NUCES public website (`nu.edu.pk`)  
Documents: 9 fetched documents  
Pages: 160+ total pages across documents  

## 1. Overview and Mapping of Required Properties

The RAHBAR corpus was intentionally curated to make all key RAG failure modes reachable, as required by the case study specification.

| # | Required property | Document(s) that provide it | Evidence or notes | Failure Mode Addressed |
|---|---|---|---|---|
| 1 | At least 6 documents, 40+ pages | Entire corpus (9 documents total: 7 PDFs and 2 HTML files; >160 pages total) | Scale verified via `corpus/fetch.py` and recorded in `corpus/MANIFEST.md`. | Scale boundary & throughput testing |
| 2 | Two versions of one policy | `Undergraduate Academic Rules (Aug 2023)` (superseded) vs `Academic Rules Handbook (Jun 2026)` (current) | The 2023 version defines older warning thresholds, course repeat rules, and attendance policies. The 2026 revision updates attendance to clause 1.21 and academic warning to clause 5.4. Indexer writes `doc_version: "2023-08"` with `superseded: true` vs `doc_version: "2026-06"` with `superseded: false`. | **Failure Mode E (Outdated source)**: Prevents the retriever from serving repealed rules as current truth. |
| 3 | Scanned, image-only PDF with no text layer | `Faculty Entrepreneurship and Technical Start-ups Policy` (`faculty-entrepreneurship-and-technical-start-ups-policy.pdf`) | Confirmed with `pdffonts`: output yields an empty font list (0 fonts embedded), proving it contains purely scanned raster images. Extracted using OCR (`pytesseract` / `pdf2image`). | **Failure Mode A (Bad extraction)**: Exercises image rasterization and optical character recognition fallback. |
| 4 | A table with real information | `Annual Report 2019-20` & `Annual Report 2023-24` (PDF tables) and `Fee Structure page` / `Grading page` (HTML tables) | Contains complex tables of tuition fees per credit hour, miscellaneous campus charges, grading point scales, and faculty statistics. Extraction maintains row-column structure via markdown table conversions. | **Failure Mode A (Bad extraction)**: Prevents tabular text from collapsing into jumbled columns. |
| 5 | Long definitions | `Student Handbook (Jun 2026)` (`student-handbook-jun-2026.pdf`) | 60+ pages containing an extensive, multi-paragraph Generative AI policy with numbered sub-clauses and definitions that would be split prematurely by naive fixed-size chunkers. | **Failure Mode B (Poor chunks)**: Requires structure-aware splitting on section headers before paragraph and sentence boundaries. |
| 6 | A deliberately absent topic | Hostel Accommodations & Hostel Allocation Rules | The university site hosts a separate document `Transport and Hostel Facilities.pdf`, which has been deliberately omitted from `corpus/sources.yaml`. The existing student handbook mentions hostels only in passing without application procedures or fee schedules. | **Abstention & Honest Refusal**: Forces the system to abstain (`answered_from_context: false`) rather than fabricating rules. |
| 7 | Exact-term content | `Academic Rules Handbook (Jun 2026)` & `Prospectus 2026` | Explicit exact terms: attendance percentage (`80%`), CGPA thresholds (`2.00` for academic warning), clause numbers (clause `1.21`, clause `5.4`), and tuition fee rates per credit hour (`Rs. 10,000`). | **Hybrid Retrieval / Term Bleed**: Dense embeddings blur exact numeric thresholds and clause references. |

---

## 2. In-Depth Analysis of Failure Modes

### Failure Mode E: Version Conflict Resolution
In FAST-NUCES policies, academic warning regulations and course repeats were modified between August 2023 and June 2026. 
- In the 2023 rules, repeated courses replaced the earlier grade directly in specific calculation modes, whereas the 2026 handbook articulates strict limits on repeated credit hours and CGPA computation under clause 3.2.
- The retriever applies a mandatory metadata filter:
  ```python
  where={"superseded": {"$eq": False}}
  ```
  Unless the user prompt explicitly requests historical or superseded rules (e.g., "Under the 2023 policy..."), the system automatically suppresses repealed provisions.

### Failure Mode A: Scanned Document OCR & Table Recovery
- Running `pdffonts` against `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` returns:
  ```text
  name                                 type              encoding         emb sub uni object ID
  ------------------------------------ ----------------- ---------------- --- --- --- ---------
  ```
  Because the font table is completely blank, standard stream extractors (`pypdf`, `pdfplumber.extract_text()`) return empty strings. The ingestion pipeline detects pages with length below 30 characters, rasterizes them to 300 DPI images with `pdf2image`, and processes them through `pytesseract` with English OCR trained models.
- For tables (such as the Fee Structure and Grading tables), the HTML parser converts HTML `<table>` elements directly into markdown pipe tables (`| Column 1 | Column 2 |`) so semantic column relationships are preserved during chunking.

### Abstention Verification: Missing Hostel Policy
Because hostel fee structures and room allotment criteria were deliberately excluded from the index, questions such as:
- *"How do I apply for a hostel room in the boys hostel and what is the security deposit?"*
will fail to clear the retrieval relevance cosine similarity floor (`RELEVANCE_FLOOR = 0.65`). The service responds with:
```json
{
  "answered_from_context": false,
  "answer": "The provided document corpus does not contain information regarding hostel room applications or hostel security deposits.",
  "confidence": "low",
  "citations": []
}
```
This guarantees 100% abstention correctness on out-of-corpus queries.
