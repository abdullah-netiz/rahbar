"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import re
from collections import Counter
from .models import Document, Page


def _is_heading(line: str) -> bool:
    """Check if line is a structural heading or section identifier that must be preserved."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    if re.match(r"^(\d+(\.\d+)*\s+[A-Z].*|Chapter\s+\d+|Section\s+\d+|Clause\s+\d+)", s, re.I):
        return True
    if s.startswith("|") and s.endswith("|"):
        return True
    return False


def clean(doc: Document) -> Document:
    """Strip repeating headers and footers that repeat across pages.
    Preserve headings, section boundaries, and markdown tables.
    """
    if len(doc.pages) <= 2:
        # Not enough pages to statistically detect repeating headers/footers
        cleaned_pages = []
        for p in doc.pages:
            cleaned_text = re.sub(r"\r\n|\r", "\n", p.text)
            cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
            cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
            cleaned_pages.append(Page(source=p.source, page=p.page, text=cleaned_text, ocr=p.ocr))
        return Document(source=doc.source, doc_version=doc.doc_version, superseded=doc.superseded, pages=cleaned_pages)

    # Count occurrence of first 2 lines (headers) and last 2 lines (footers) across pages
    edge_lines: Counter[str] = Counter()
    for p in doc.pages:
        lines = [line.strip() for line in p.text.splitlines() if line.strip()]
        if len(lines) >= 1:
            edge_lines[lines[0]] += 1
        if len(lines) >= 2:
            edge_lines[lines[1]] += 1
        if len(lines) >= 3:
            edge_lines[lines[-1]] += 1
        if len(lines) >= 4:
            edge_lines[lines[-2]] += 1

    # Any non-heading edge line appearing on > 30% of pages is considered repeating artefact
    threshold = max(3, int(len(doc.pages) * 0.3))
    repeating = {line for line, count in edge_lines.items() if count >= threshold and not _is_heading(line)}

    cleaned_pages = []
    for p in doc.pages:
        raw_lines = p.text.splitlines()
        filtered_lines = []
        for line in raw_lines:
            s = line.strip()
            # Filter repeating header/footer or bare page numbers
            if s in repeating and not _is_heading(s):
                continue
            if re.match(r"^(Page\s+\d+(\s+of\s+\d+)?|\d+)$", s, re.I):
                continue
            filtered_lines.append(line)

        cleaned_text = "\n".join(filtered_lines)
        cleaned_text = re.sub(r"\r\n|\r", "\n", cleaned_text)
        cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
        cleaned_pages.append(Page(source=p.source, page=p.page, text=cleaned_text, ocr=p.ocr))

    return Document(source=doc.source, doc_version=doc.doc_version, superseded=doc.superseded, pages=cleaned_pages)
