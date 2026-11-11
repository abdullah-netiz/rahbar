"""Comprehensive tests for the extraction, cleaning, chunking and embedding pipeline."""

from __future__ import annotations

import math
from pathlib import Path
from pipeline.models import Document, Page
from pipeline.extract import extract
from pipeline.clean import clean
from pipeline.chunk import chunk, calculate_storage_amplification
from pipeline.embed import embed, _deterministic_fallback_embed
from pipeline.config import get_settings


def test_extract_markdown_fixture() -> None:
    fixture_path = Path(__file__).resolve().parent.parent.parent / "eval" / "fixtures" / "academic-rules-2026.md"
    doc = extract(str(fixture_path), "2026", False)
    assert doc.source == "academic-rules-2026.md"
    assert doc.doc_version == "2026"
    assert not doc.superseded
    assert len(doc.pages) == 1
    assert "Attendance" in doc.pages[0].text
    assert not doc.pages[0].ocr


def test_clean_repeating_headers() -> None:
    # Build a 5-page document with repeating header and footer
    pages = []
    for i in range(1, 6):
        text = f"FAST-NUCES Annual Policy\n## {i}. Academic Rule {i}\nBody content of page {i}.\nPage {i} of 5"
        pages.append(Page(source="test.pdf", page=i, text=text, ocr=False))

    doc = Document(source="test.pdf", doc_version="2026", superseded=False, pages=pages)
    cleaned = clean(doc)

    for p in cleaned.pages:
        # Repeating header and footer stripped
        assert "FAST-NUCES Annual Policy" not in p.text
        assert "Page" not in p.text
        # Heading and body preserved
        assert "Academic Rule" in p.text
        assert "Body content" in p.text


def test_chunking_structure_aware_and_overlap() -> None:
    text = (
        "## 1. Attendance\n"
        "A student must attend at least 80 percent of lectures to sit the exam. "
        "Failure to meet attendance leads to an FA grade.\n\n"
        "## 2. Academic Warning\n"
        "A student whose CGPA falls below 2.00 is placed on academic warning. "
        "Three warnings lead to expulsion."
    )
    doc = Document(source="rules.md", doc_version="2026", superseded=False, pages=[Page(source="rules.md", page=1, text=text)])
    chunks = chunk(doc, size=20, overlap=5)

    assert len(chunks) >= 2
    # Check section assignment
    sections = [c.section for c in chunks]
    assert any("Attendance" in s for s in sections)
    assert any("Academic Warning" in s for s in sections)

    # Check metadata integrity
    for c in chunks:
        assert c.source == "rules.md"
        assert c.doc_version == "2026"
        assert not c.superseded
        assert c.page == 1
        assert c.id.startswith("rules.md-p1-c")


def test_calculate_storage_amplification() -> None:
    text = "Word " * 100
    doc = Document(source="test.md", doc_version="2026", superseded=False, pages=[Page(source="test.md", page=1, text=text)])
    chunks = chunk(doc, size=40, overlap=10)
    amp = calculate_storage_amplification(doc, chunks)
    assert amp >= 1.0


def test_deterministic_embedding() -> None:
    v1 = _deterministic_fallback_embed("test text", dim=768)
    v2 = _deterministic_fallback_embed("test text", dim=768)
    v3 = _deterministic_fallback_embed("different text", dim=768)

    assert len(v1) == 768
    assert v1 == v2
    assert v1 != v3

    # Check vector unit norm
    norm = math.sqrt(sum(x * x for x in v1))
    assert math.isclose(norm, 1.0, rel_tol=1e-4)


def test_embed_batch_fallback() -> None:
    settings = get_settings()
    texts = ["First passage to embed", "Second passage to embed"]
    vectors = embed(texts, settings)
    assert len(vectors) == 2
    assert len(vectors[0]) == 768
    assert len(vectors[1]) == 768

