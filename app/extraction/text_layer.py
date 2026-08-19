import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
MIN_TABLE_FILL = 0.5

PAGE_MARKER = "--- PAGE {n} ---"
TABLE_MARKER = "--- TABLE ---"
CELL_SEPARATOR = " | "


class ExtractionError(Exception):
    pass


def _is_useful(table: list[list[str | None]]) -> bool:
    cols = max((len(row) for row in table), default=0)
    if len(table) < MIN_TABLE_ROWS or cols < MIN_TABLE_COLS:
        return False

    cells = [c for row in table for c in row]
    if not cells:
        return False

    filled = sum(1 for c in cells if c and c.strip())
    return filled / len(cells) >= MIN_TABLE_FILL


def _table_to_text(table: list[list[str | None]]) -> str:
    lines = []
    for row in table:
        cells = [(c or "").strip().replace("\n", " ") for c in row]
        if any(cells):
            lines.append(CELL_SEPARATOR.join(cells))
    return "\n".join(lines)


def _tidy(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _extract_page(page: pdfplumber.page.Page, layout: bool) -> list[str]:
    parts: list[str] = []

    text = _tidy(page.extract_text(layout=layout) or "")
    if text:
        parts.append(text)

    for table in page.extract_tables():
        if not _is_useful(table):
            continue
        rendered = _table_to_text(table)
        if rendered:
            parts.append(TABLE_MARKER)
            parts.append(rendered)

    return parts


def extract_text_layer(
    pdf_path: Path | str,
    *,
    layout: bool = False,
    max_pages: int | None = None,
) -> tuple[str, int]:
    path = Path(pdf_path)
    if not path.is_file():
        raise ExtractionError(f"File not found: {path}")

    try:
        pdf = pdfplumber.open(path)
    except Exception as e:
        raise ExtractionError(f"Cannot open PDF '{path.name}': {e}") from e

    parts: list[str] = []

    with pdf:
        page_count = len(pdf.pages)
        if page_count == 0:
            raise ExtractionError(f"PDF '{path.name}' has no pages")

        pages = pdf.pages[:max_pages] if max_pages else pdf.pages

        for i, page in enumerate(pages, start=1):
            try:
                page_parts = _extract_page(page, layout)
            except Exception as e:
                logger.warning("Skipping page %d of '%s': %s", i, path.name, e)
                continue

            if page_parts:
                parts.append(PAGE_MARKER.format(n=i))
                parts.extend(page_parts)

    return "\n".join(parts), page_count
