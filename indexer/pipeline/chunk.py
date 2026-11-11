"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import re
from .models import Chunk, Document


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences while respecting periods inside numbers or abbreviations."""
    sentence_end = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])|\n+')
    parts = sentence_end.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_into_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _detect_heading(line: str) -> str | None:
    """Detect structural headings.
    Distinguishes section headings (e.g. '## 1. Attendance' or '1. Attendance')
    from numbered paragraph bodies (e.g. '1.1 A student must attend...').
    """
    s = line.strip()
    if not s:
        return None
    # Markdown headers
    if s.startswith("#"):
        return s.lstrip("#").strip()
    # Explicit section/chapter keywords
    if re.match(r"^(Chapter|Section|Part|Clause)\s+\d+.*", s, re.I) and len(s) < 80:
        return s
    # Numbered heading pattern: e.g. "1. Attendance", "5.4 Academic Warning", "2. Academic warning"
    # Key criteria: relatively short (< 70 chars), doesn't end with a period, or has no long sentence punctuation
    m = re.match(r"^(\d+(\.\d+)*)\s+([A-Z][^.\n]{2,60})$", s)
    if m:
        return s
    return None


def calculate_storage_amplification(doc: Document, chunks: list[Chunk]) -> float:
    """Calculate storage amplification: stored tokens divided by original tokens.
    Uses whitespace word-split as token approximation (~1.3 tokens/word).
    """
    orig_words = sum(len(p.text.split()) for p in doc.pages) or 1
    chunk_words = sum(len(c.text.split()) for c in chunks)
    return round(chunk_words / orig_words, 3)


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Structure-aware chunking with overlap.
    Splits on section boundaries, then paragraphs, then sentences, keeping chunks
    under `size` tokens with `overlap` tokens shared between consecutive chunks.
    Every chunk records its source, section, page, doc_version and superseded.
    """
    chunks: list[Chunk] = []
    chunk_counter = 0

    for p in doc.pages:
        paragraphs = _split_into_paragraphs(p.text)
        current_section = f"General ({p.source})"

        current_tokens: list[str] = []
        current_text_units: list[str] = []

        for para in paragraphs:
            first_line = para.splitlines()[0]
            detected = _detect_heading(first_line)
            if detected:
                # Flush previous buffer before entering new section
                if current_text_units:
                    chunk_text = " ".join(current_text_units).strip()
                    if chunk_text:
                        chunk_counter += 1
                        stable_id = f"{doc.source}-p{p.page}-c{chunk_counter:04d}"
                        chunks.append(
                            Chunk(
                                id=stable_id,
                                text=chunk_text,
                                source=doc.source,
                                section=current_section,
                                page=p.page,
                                doc_version=doc.doc_version,
                                superseded=doc.superseded,
                            )
                        )
                    current_tokens = []
                    current_text_units = []

                current_section = detected
                # If paragraph has more lines beyond the heading, use remainder as body
                rest_lines = para.splitlines()[1:]
                para_body = "\n".join(rest_lines).strip()
            else:
                para_body = para

            if not para_body:
                continue

            sentences = _split_into_sentences(para_body)
            for sentence in sentences:
                sent_words = sentence.split()
                if not sent_words:
                    continue

                if len(current_tokens) + len(sent_words) <= size:
                    current_tokens.extend(sent_words)
                    current_text_units.append(sentence)
                else:
                    if current_text_units:
                        chunk_text = " ".join(current_text_units).strip()
                        if chunk_text:
                            chunk_counter += 1
                            stable_id = f"{doc.source}-p{p.page}-c{chunk_counter:04d}"
                            chunks.append(
                                Chunk(
                                    id=stable_id,
                                    text=chunk_text,
                                    source=doc.source,
                                    section=current_section,
                                    page=p.page,
                                    doc_version=doc.doc_version,
                                    superseded=doc.superseded,
                                )
                            )

                    if overlap > 0 and len(current_tokens) > overlap:
                        overlap_words = current_tokens[-overlap:]
                        current_tokens = list(overlap_words) + sent_words
                        current_text_units = [" ".join(overlap_words), sentence]
                    else:
                        current_tokens = list(sent_words)
                        current_text_units = [sentence]

        if current_text_units:
            chunk_text = " ".join(current_text_units).strip()
            if chunk_text:
                chunk_counter += 1
                stable_id = f"{doc.source}-p{p.page}-c{chunk_counter:04d}"
                chunks.append(
                    Chunk(
                        id=stable_id,
                        text=chunk_text,
                        source=doc.source,
                        section=current_section,
                        page=p.page,
                        doc_version=doc.doc_version,
                        superseded=doc.superseded,
                    )
                )

    return chunks
