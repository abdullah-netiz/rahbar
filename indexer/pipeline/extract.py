"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from .models import Document, Page


class _HTMLToMarkdownParser(HTMLParser):
    """Basic HTML to structured Markdown parser preserving headers and tables."""

    def __init__(self) -> None:
        super().__init__()
        self.output: list[str] = []
        self.in_table = False
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.is_header_row = False
        self.table_rows: list[list[str]] = []
        self.heading_level = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_level = int(tag_lower[1])
            self.output.append(f"\n\n{'#' * self.heading_level} ")
        elif tag_lower == "p":
            self.output.append("\n\n")
        elif tag_lower == "br":
            self.output.append("\n")
        elif tag_lower == "table":
            self.in_table = True
            self.table_rows = []
        elif tag_lower == "tr":
            self.current_row = []
            self.is_header_row = False
        elif tag_lower in ("th", "td"):
            self.current_cell = []
            if tag_lower == "th":
                self.is_header_row = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_level = 0
            self.output.append("\n\n")
        elif tag_lower in ("th", "td"):
            cell_text = "".join(self.current_cell).strip().replace("|", "\\|")
            self.current_row.append(cell_text)
        elif tag_lower == "tr":
            if self.current_row:
                self.table_rows.append(self.current_row)
        elif tag_lower == "table":
            self.in_table = False
            if self.table_rows:
                self.output.append("\n\n")
                # format markdown table
                max_cols = max(len(row) for row in self.table_rows)
                # pad rows
                norm_rows = [row + [""] * (max_cols - len(row)) for row in self.table_rows]
                header = norm_rows[0]
                self.output.append("| " + " | ".join(header) + " |\n")
                self.output.append("| " + " | ".join(["---"] * max_cols) + " |\n")
                for row in norm_rows[1:]:
                    self.output.append("| " + " | ".join(row) + " |\n")
                self.output.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_table:
            self.current_cell.append(data)
        else:
            self.output.append(data)

    def get_text(self) -> str:
        return "".join(self.output).strip()


def _extract_pdf(path: Path, source_name: str) -> list[Page]:
    pages: list[Page] = []
    import pdfplumber
    import pypdf

    # Attempt pdfplumber extraction first
    try:
        with pdfplumber.open(path) as pdf:
            for idx, p in enumerate(pdf.pages, start=1):
                text = p.extract_text() or ""
                # Also extract tables if present
                tables = p.extract_tables() or []
                if tables:
                    table_mds = []
                    for tbl in tables:
                        if tbl and any(any(c for c in row if c) for row in tbl):
                            cols = max(len(r) for r in tbl)
                            cleaned_rows = [
                                [str(c or "").strip().replace("\n", " ").replace("|", "\\|") for c in r]
                                + [""] * (cols - len(r))
                                for r in tbl
                            ]
                            if cleaned_rows:
                                t_str = "| " + " | ".join(cleaned_rows[0]) + " |\n"
                                t_str += "| " + " | ".join(["---"] * cols) + " |\n"
                                for r in cleaned_rows[1:]:
                                    t_str += "| " + " | ".join(r) + " |\n"
                                table_mds.append(t_str)
                    if table_mds:
                        text = text + "\n\n" + "\n\n".join(table_mds)

                ocr = False
                # If extracted text is essentially empty, fall back to OCR
                if len(text.strip()) < 30:
                    try:
                        import pdf2image
                        import pytesseract

                        images = pdf2image.convert_from_path(path, first_page=idx, last_page=idx)
                        if images:
                            ocr_text = pytesseract.image_to_string(images[0])
                            if len(ocr_text.strip()) > len(text.strip()):
                                text = ocr_text
                                ocr = True
                    except Exception:
                        pass
                pages.append(Page(source=source_name, page=idx, text=text, ocr=ocr))
    except Exception:
        # Fallback to pypdf
        reader = pypdf.PdfReader(str(path))
        for idx, py_page in enumerate(reader.pages, start=1):
            text = py_page.extract_text() or ""
            ocr = False
            if len(text.strip()) < 30:
                try:
                    import pdf2image
                    import pytesseract

                    images = pdf2image.convert_from_path(path, first_page=idx, last_page=idx)
                    if images:
                        text = pytesseract.image_to_string(images[0])
                        ocr = True
                except Exception:
                    pass
            pages.append(Page(source=source_name, page=idx, text=text, ocr=ocr))

    return pages


def _extract_html(path: Path, source_name: str) -> list[Page]:
    raw_html = path.read_text(encoding="utf-8", errors="replace")
    parser = _HTMLToMarkdownParser()
    parser.feed(raw_html)
    text = parser.get_text()
    return [Page(source=source_name, page=1, text=text, ocr=False)]


def _extract_text(path: Path, source_name: str) -> list[Page]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Strip YAML front matter if present
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    return [Page(source=source_name, page=1, text=text, ocr=False)]


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detects pages with no text layer and runs OCR (pytesseract, pdf2image).
    Handles PDF, HTML, and Markdown/plain-text documents.
    """
    file_path = Path(path)
    source_name = file_path.name
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        pages = _extract_pdf(file_path, source_name)
    elif suffix in (".html", ".htm"):
        pages = _extract_html(file_path, source_name)
    else:
        pages = _extract_text(file_path, source_name)

    return Document(source=source_name, doc_version=doc_version, superseded=superseded, pages=pages)
