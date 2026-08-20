"""Gatekeeper: everything a PDF must survive before any parsing happens.

Runs cheapest check first - stat, then magic bytes, then a structural
parse - so a 500 MB video renamed to .pdf is rejected without ever being
read into memory, and a 200-page document is rejected before it can tie
up the OCR path.

Only pdfminer is used here: it ships with pdfplumber, walks the object
tree without rendering anything, and lets us tell "encrypted" apart from
"corrupt", which pdfplumber alone does not.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from pdfminer.pdfdocument import (
    PDFDocument,
    PDFEncryptionError,
    PDFPasswordIncorrect,
)
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSException

from app.services.errors import (
    EmptyDocumentError,
    EncryptedPDFError,
    FileTooLargeError,
    InvalidPDFError,
    SourceNotFoundError,
    TooManyPagesError,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES = 10

PDF_MAGIC = b"%PDF-"
# The header is allowed to sit anywhere in the first 1024 bytes; readers
# tolerate leading junk from mail gateways, and so do we.
HEADER_WINDOW = 1024


@dataclass(frozen=True)
class PdfInfo:
    """What validation learned, so the caller need not re-open the file."""

    path: Path
    size_bytes: int
    page_count: int


def _check_file(path: Path, max_size_bytes: int) -> int:
    try:
        stat = path.stat()
    except FileNotFoundError as e:
        raise SourceNotFoundError("File not found", filename=path.name) from e
    except OSError as e:
        # Never echo the absolute path outward - it reaches the API response.
        raise SourceNotFoundError(
            f"Cannot read file: {e.strerror or e}", filename=path.name
        ) from e

    if not path.is_file():
        raise SourceNotFoundError("Not a regular file", filename=path.name)

    if stat.st_size == 0:
        raise InvalidPDFError("File is empty", filename=path.name)

    if stat.st_size > max_size_bytes:
        raise FileTooLargeError(
            f"File is {stat.st_size / 1024 / 1024:.1f} MB, "
            f"limit is {max_size_bytes / 1024 / 1024:.0f} MB",
            filename=path.name,
        )

    return stat.st_size


def _check_magic(path: Path) -> None:
    try:
        with path.open("rb") as fh:
            head = fh.read(HEADER_WINDOW)
    except OSError as e:
        raise InvalidPDFError(f"Cannot read file: {e}", filename=path.name) from e

    if PDF_MAGIC not in head:
        raise InvalidPDFError(
            "Not a PDF: missing %PDF- header (the extension is not evidence)",
            filename=path.name,
        )


def _page_count(document: PDFDocument, path: Path) -> int:
    """Page count from the catalogue, falling back to walking the tree."""
    try:
        pages = resolve1(document.catalog["Pages"])
        count = resolve1(pages["Count"])
        if isinstance(count, int) and count >= 0:
            return count
    except Exception:
        logger.debug("'%s': no usable /Count, walking the page tree", path.name)

    try:
        return sum(1 for _ in PDFPage.create_pages(document))
    except Exception as e:
        raise InvalidPDFError(f"Cannot read page tree: {e}", filename=path.name) from e


def _check_structure(path: Path, max_pages: int) -> int:
    with path.open("rb") as fh:
        try:
            document = PDFDocument(PDFParser(fh))
        except (PDFPasswordIncorrect, PDFEncryptionError) as e:
            # PDFPasswordIncorrect carries no message of its own.
            detail = f": {e}" if str(e) else ""
            raise EncryptedPDFError(
                "PDF is password-protected or uses unsupported "
                f"encryption{detail}",
                filename=path.name,
            ) from e
        except (PDFSyntaxError, PSException) as e:
            raise InvalidPDFError(f"Corrupt PDF: {e}", filename=path.name) from e
        except Exception as e:
            raise InvalidPDFError(f"Cannot parse PDF: {e}", filename=path.name) from e

        count = _page_count(document, path)

    if count == 0:
        raise EmptyDocumentError("PDF contains no pages", filename=path.name)

    if count > max_pages:
        raise TooManyPagesError(
            f"PDF has {count} pages, limit is {max_pages}",
            filename=path.name,
        )

    return count


def validate_pdf(
    pdf_path: Path | str,
    *,
    max_size_bytes: int = MAX_FILE_SIZE_BYTES,
    max_pages: int = MAX_PAGES,
) -> PdfInfo:
    """Reject anything the pipeline should not spend time on.

    Raises a subclass of ExtractionError - never a pdfminer exception.
    """
    path = Path(pdf_path)

    size_bytes = _check_file(path, max_size_bytes)
    _check_magic(path)
    page_count = _check_structure(path, max_pages)

    logger.debug(
        "'%s': valid PDF, %d page(s), %.1f KB",
        path.name,
        page_count,
        size_bytes / 1024,
    )
    return PdfInfo(path=path, size_bytes=size_bytes, page_count=page_count)
