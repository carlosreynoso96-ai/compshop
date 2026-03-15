"""
Stage 1: Scan folder, qualify PDFs by property keyword in filename.
Stage 2: Extract text from qualifying PDFs using pypdf.
Stage 2b: Automatic OCR fallback for scanned / image-only pages.
"""

import io
import logging
import re
from pathlib import Path
from dataclasses import dataclass, field

import pypdf

log = logging.getLogger(__name__)

# ── OCR constants ───────────────────────────────────────────
OCR_CHAR_THRESHOLD = 50  # pages with fewer chars are considered scanned
OCR_DPI = 300  # render resolution for OCR


def _ocr_available() -> bool:
    """Return True if pymupdf + pytesseract + Tesseract binary are all usable."""
    try:
        import fitz  # noqa: F401  (PyMuPDF)
        import pytesseract

        # Quick sanity check — will raise if tesseract binary missing
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_page_image(pdf_path: Path, page_index: int) -> str:
    """Render *one* PDF page to an image and run Tesseract OCR on it."""
    import fitz
    import pytesseract
    from PIL import Image

    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    mat = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img)
    doc.close()
    return text.strip()


@dataclass
class PDFDocument:
    filename: str
    filepath: Path
    segment_code: str
    pages: list[dict] = field(default_factory=list)
    total_chars: int = 0
    ocr_applied: bool = False


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


def extract_text(pdf_paths, *, enable_ocr: bool = True):
    """
    Stage 2: Extract text from each qualifying PDF.
    If *enable_ocr* is True and a page yields < OCR_CHAR_THRESHOLD chars,
    the page is rendered to an image and run through Tesseract OCR.
    Returns list of PDFDocument objects with text and metadata.
    """
    ocr_ok = enable_ocr and _ocr_available()
    if enable_ocr and not ocr_ok:
        log.warning(
            "OCR requested but pymupdf/pytesseract/Tesseract not available — skipping OCR"
        )

    documents = []
    for pdf_path in pdf_paths:
        reader = pypdf.PdfReader(str(pdf_path))
        pages = []
        total = 0
        used_ocr = False

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            source = "text"

            # ── OCR fallback for scanned / image-only pages ─────
            if ocr_ok and len(text.strip()) < OCR_CHAR_THRESHOLD:
                try:
                    ocr_text = _ocr_page_image(pdf_path, i)
                    if len(ocr_text) > len(text):
                        text = ocr_text
                        source = "ocr"
                        used_ocr = True
                except Exception as exc:
                    log.warning(
                        "OCR failed on %s page %d: %s", pdf_path.name, i + 1, exc
                    )

            pages.append({"page": i + 1, "text": text, "source": source})
            total += len(text)

        doc = PDFDocument(
            filename=pdf_path.name,
            filepath=pdf_path,
            segment_code=extract_segment_code(pdf_path.name),
            pages=pages,
            total_chars=total,
            ocr_applied=used_ocr,
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
