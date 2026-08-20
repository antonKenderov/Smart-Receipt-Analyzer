import logging
from pathlib import Path

from app.domain.models import ExtractionMethod, ExtractionResult
from app.extraction.image_reader import images_reader
from app.extraction.pdf_reader import pdf_to_images
from app.extraction.text_layer import ExtractionError, extract_text_layer

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 100
MAX_PAGES = 10


def has_usable_text_layer(text: str, page_count: int) -> bool:
    if page_count <= 0:
        return False
    return len(text.strip()) / page_count >= MIN_CHARS_PER_PAGE


def _ocr(pdf_path: Path, pages_read: int) -> tuple[str, int]:
    try:
        images = pdf_to_images(pdf_path, max_pages=pages_read)
    except Exception as e:
        raise ExtractionError(f"Cannot rasterise '{pdf_path.name}': {e}") from e

    if not images:
        raise ExtractionError(f"Rasterising '{pdf_path.name}' produced no pages")

    return images_reader(images)


def extract_text(pdf_path: Path) -> ExtractionResult:
    path = Path(pdf_path)
    warnings: list[str] = []
    text, page_count = extract_text_layer(path, layout=True, max_pages=MAX_PAGES)

    pages_read = min(page_count, MAX_PAGES)
    if page_count > pages_read:
        warnings.append(
            f"Document has {page_count} pages, only the first {pages_read} were read"
        )

    if has_usable_text_layer(text, pages_read):
        logger.info("'%s': using embedded text layer", path.name)
        text = text.strip()
        return ExtractionResult(
            text=text,
            method=ExtractionMethod.TEXT_LAYER,
            page_count=page_count,
            char_count=len(text),
            warnings=warnings,
        )

    density = len(text.strip()) / pages_read if pages_read else 0.0
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

    text, dropped = _ocr(path, pages_read)
    text = text.strip()

    if not text:
        raise ExtractionError(f"Neither text layer nor OCR found text in '{path.name}'")

    if dropped:
        warnings.append(f"OCR discarded {dropped} low-confidence fragments")

    return ExtractionResult(
        text=text,
        method=ExtractionMethod.OCR,
        page_count=page_count,
        char_count=len(text),
        warnings=warnings,
    )
