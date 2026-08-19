from pathlib import Path

from pdf2image import convert_from_path
from PIL.Image import Image


def pdf_to_images(pdf_path: str | Path, dpi: int = 200) -> list[Image]:
    return convert_from_path(str(pdf_path), dpi=dpi)


def folder_to_images(folder_path: str | Path, dpi: int = 200) -> dict[str, list[Image]]:
    folder = Path(folder_path)
    pdf_files = sorted(folder.glob("*.pdf"))

    return {
        pdf_file.name: pdf_to_images(pdf_file, dpi=dpi)
        for pdf_file in pdf_files
    }
