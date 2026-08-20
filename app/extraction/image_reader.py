import logging
from statistics import median

import easyocr
import numpy as np
from PIL.Image import Image

logger = logging.getLogger(__name__)

OCR_LANGUAGES = ["en", "bg"]
MIN_CONFIDENCE = 0.3
Y_TOLERANCE_RATIO = 0.5
PAGE_MARKER = "--- PAGE {n} ---"

_reader: easyocr.Reader | None = None


def get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        logger.info("Loading EasyOCR models for %s", OCR_LANGUAGES)
        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
    return _reader


def image_reader(image: Image) -> list:
    return get_reader().readtext(np.array(image))


def to_lines(
    results: list,
    *,
    y_tolerance: float | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> tuple[list[str], int]:
    if not results:
        return [], 0

    items: list[tuple[float, float, str]] = []
    heights: list[float] = []
    dropped = 0

    for bbox, text, conf in results:
        if conf < min_confidence or not text.strip():
            dropped += 1
            continue
        ys = [p[1] for p in bbox]
        items.append((sum(ys) / len(ys), min(p[0] for p in bbox), text))
        heights.append(max(ys) - min(ys))

    if not items:
        return [], dropped

    if y_tolerance is None:
        y_tolerance = median(heights) * Y_TOLERANCE_RATIO

    items.sort(key=lambda it: it[0])

    lines: list[list[tuple[float, float, str]]] = []
    current = [items[0]]

    for item in items[1:]:
        if abs(item[0] - current[-1][0]) <= y_tolerance:
            current.append(item)
        else:
            lines.append(current)
            current = [item]
    lines.append(current)

    rendered = [
        " ".join(w[2] for w in sorted(line, key=lambda it: it[1]))
        for line in lines
    ]
    return rendered, dropped


def images_reader(images: list[Image]) -> tuple[str, int]:
    parts: list[str] = []
    total_dropped = 0

    for i, image in enumerate(images, start=1):
        lines, dropped = to_lines(image_reader(image))
        total_dropped += dropped
        if lines:
            parts.append(PAGE_MARKER.format(n=i))
            parts.extend(lines)

    return "\n".join(parts), total_dropped