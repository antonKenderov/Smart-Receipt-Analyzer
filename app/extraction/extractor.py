import logging
from pathlib import Path

from app.domain.extraction import ExtractionMethod, ExtractionResult
from app.extraction.image_reader import images_reader
from app.extraction.pdf_reader import pdf_to_images
from app.extraction.text_layer import extract_text_layer
from app.extraction.validation import PdfInfo, validate_pdf
from app.services.errors import InvalidPDFError, NoTextFoundError

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 100

# Costs ~1.5x the tokens of layout=False, and buys the horizontal
# alignment that keeps the issuer block apart from the receiver block -
# without it the two columns of the header merge into single lines.
USE_LAYOUT = True


def has_usable_text_layer(text: str, page_count: int) -> bool:
    if page_count <= 0:
        return False
    return len(text.strip()) / page_count >= MIN_CHARS_PER_PAGE


def _ocr(info: PdfInfo) -> tuple[str, int]:
    try:
        images = pdf_to_images(info.path)
    except Exception as e:
        raise InvalidPDFError(
            f"Cannot rasterise for OCR: {e}", filename=info.path.name
        ) from e

    if not images:
        raise InvalidPDFError("Rasterising produced no pages", filename=info.path.name)

    return images_reader(images)


def extract_text(pdf_path: Path) -> ExtractionResult:
    info = validate_pdf(pdf_path)
    path = info.path
    warnings: list[str] = []

    text, page_count = extract_text_layer(path, layout=USE_LAYOUT)

    if has_usable_text_layer(text, page_count):
        logger.info("'%s': using embedded text layer", path.name)
        text = text.strip()
        return ExtractionResult(
            text=text,
            method=ExtractionMethod.TEXT_LAYER,
            page_count=page_count,
            char_count=len(text),
            warnings=warnings,
        )

    density = len(text.strip()) / page_count if page_count else 0.0
    logger.info(
        "'%s': text layer too thin (%.0f chars/page < %d), falling back to OCR",
        path.name,
        density,
        MIN_CHARS_PER_PAGE,
    )
    warnings.append(
        f"Text layer held {density:.0f} chars/page "
        f"(below {MIN_CHARS_PER_PAGE}), fell back to OCR"
    )

    text, dropped = _ocr(info)
    text = text.strip()

    if not text:
        raise NoTextFoundError(
            "Neither the text layer nor OCR found any text", filename=path.name
        )

    if dropped:
        warnings.append(f"OCR discarded {dropped} low-confidence fragments")

    return ExtractionResult(
        text=text,
        method=ExtractionMethod.OCR,
        page_count=page_count,
        char_count=len(text),
        warnings=warnings,
    )
