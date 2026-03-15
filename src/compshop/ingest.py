"""
Stage 1: Scan folder, qualify PDFs by property keyword in filename.
Stage 2: Extract text from qualifying PDFs using pypdf.
"""

import re
from pathlib import Path
from dataclasses import dataclass, field

import pypdf


@dataclass
class PDFDocument:
    filename: str
    filepath: Path
    segment_code: str
    pages: list[dict] = field(default_factory=list)
    total_chars: int = 0


def extract_segment_code(filename):
    """Extract segment code from filename prefix (everything before first '-')."""
    match = re.match(r"^([A-Za-z0-9$]+)", filename)
    return match.group(1) if match else "NA"


def scan_and_qualify(input_dir, property_keyword, latest_only=False):
    """
    Stage 1: Scan directory for PDFs matching property keyword.
    Returns list of qualifying PDF paths sorted by filename desc.
    """
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    all_pdfs = sorted(input_path.glob("*.pdf"), key=lambda p: p.name, reverse=True)

    # Qualify: filename must reference the property keyword
    keyword_upper = property_keyword.upper()
    qualifying = []
    for pdf_path in all_pdfs:
        if keyword_upper in pdf_path.name.upper():
            qualifying.append(pdf_path)

    if latest_only and qualifying:
        qualifying = [qualifying[0]]

    return qualifying


def extract_text(pdf_paths):
    """
    Stage 2: Extract text from each qualifying PDF.
    Returns list of PDFDocument objects with text and metadata.
    """
    documents = []
    for pdf_path in pdf_paths:
        reader = pypdf.PdfReader(str(pdf_path))
        pages = []
        total = 0
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append({"page": i + 1, "text": text})
            total += len(text)

        doc = PDFDocument(
            filename=pdf_path.name,
            filepath=pdf_path,
            segment_code=extract_segment_code(pdf_path.name),
            pages=pages,
            total_chars=total,
        )
        documents.append(doc)

    return documents


def build_batch_content(documents, property_name, competitor_name):
    """
    Build the user message content for a batch of PDFs.
    Returns the string to send as the user message.
    """
    lines = [
        f"Property: {property_name}",
        f"Competitor: {competitor_name}",
        "",
        "Below are the extracted text contents from casino promotional email PDFs.",
        "Extract ALL gaming-related offers, deduplicate across PDFs, expand recurring dates, and return the JSON array.",
        "",
    ]

    for doc in documents:
        lines.append("=" * 60)
        lines.append(f"FILENAME: {doc.filename}")
        lines.append("=" * 60)
        for page in doc.pages:
            lines.append(f"\n--- Page {page['page']} ---")
            lines.append(page["text"])
        lines.append("")

    return "\n".join(lines)
