from pathlib import Path

from pdf2image import convert_from_path
from PIL.Image import Image

DEFAULT_DPI = 200


def pdf_to_images(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
    max_pages: int | None = None,
) -> list[Image]:
    kwargs = {"dpi": dpi}
    if max_pages:
        kwargs["last_page"] = max_pages
    return convert_from_path(str(pdf_path), **kwargs)