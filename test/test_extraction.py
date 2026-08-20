from pathlib import Path

import pytest

from app.domain.extraction import ExtractionMethod
from app.extraction.extractor import (
    MIN_CHARS_PER_PAGE,
    USE_LAYOUT,
    extract_text,
    has_usable_text_layer,
)
from app.extraction.image_reader import to_lines
from app.extraction.text_layer import extract_text_layer
from app.extraction.validation import MAX_PAGES, validate_pdf
from conftest import SAMPLES
from app.services.errors import EncryptedPDFError, ExtractionError, TooManyPagesError


def test_digital_pdf_uses_text_layer(digital_pdf: Path):
    result = extract_text(digital_pdf)

    assert result.method is ExtractionMethod.TEXT_LAYER
    assert result.page_count == 1
    assert result.char_count == len(result.text) > 0
    assert result.warnings == []
    assert "OfficePro" in result.text
    assert "USB Flash Drive 32GB" in result.text


@pytest.mark.slow
def test_scanned_pdf_falls_back_to_ocr(scanned_pdf: Path):
    result = extract_text(scanned_pdf)

    assert result.method is ExtractionMethod.OCR
    assert result.page_count == 1
    assert result.char_count == len(result.text) > 0
    assert any("fell back to OCR" in w for w in result.warnings)
    assert "OPS-8847" in result.text


def test_encrypted_pdf_raises(encrypted_pdf: Path):
    with pytest.raises(EncryptedPDFError) as excinfo:
        extract_text(encrypted_pdf)

    error = excinfo.value
    assert isinstance(error, ExtractionError)
    assert error.code == "encrypted_pdf"
    assert error.status == 400
    assert str(encrypted_pdf.parent) not in str(error)


def test_line_grouping(bbox):
    results = [
        (bbox(1160, 1207, 1300, 1239), "12.75", 0.9),
        (bbox(250, 1200, 260, 1232), "3", 0.9),
        (bbox(300, 1203, 700, 1235), "Desk Organizer", 0.9),
        (bbox(980, 1205, 1010, 1237), "6", 0.9),
        (bbox(250, 1240, 260, 1272), "4", 0.9),
        (bbox(300, 1243, 700, 1275), "Wireless Mouse", 0.9),
        (bbox(980, 1245, 1010, 1277), "8", 0.9),
        (bbox(1160, 1247, 1300, 1279), "18.90", 0.9),
        (bbox(400, 1400, 420, 1432), "~", 0.1),
        (bbox(500, 1400, 520, 1432), "   ", 0.9),
    ]

    lines, dropped = to_lines(results)

    assert lines == [
        "3 Desk Organizer 6 12.75",
        "4 Wireless Mouse 8 18.90",
    ]
    assert dropped == 2


def test_page_limit_enforced(blank_pdf):
    at_limit = blank_pdf(MAX_PAGES)
    over_limit = blank_pdf(MAX_PAGES + 1)

    assert validate_pdf(at_limit).page_count == MAX_PAGES

    with pytest.raises(TooManyPagesError) as excinfo:
        validate_pdf(over_limit)

    assert excinfo.value.status == 413
    assert str(MAX_PAGES) in str(excinfo.value)

    with pytest.raises(TooManyPagesError):
        extract_text(over_limit)


SCANNED_SAMPLES = {"8.pdf", "7_scanned.pdf"}


def _text_and_pages(pdf: Path) -> tuple[str, int]:
    return extract_text_layer(pdf, layout=USE_LAYOUT)


def _density(pdf: Path) -> float:
    text, page_count = extract_text_layer(pdf, layout=USE_LAYOUT)
    return len(text.strip()) / page_count


@pytest.mark.parametrize("pdf", sorted(SAMPLES.glob("*.pdf")), ids=lambda p: p.name)
def test_sample_lands_on_the_expected_side_of_the_threshold(pdf: Path):
    density = _density(pdf)

    if pdf.name in SCANNED_SAMPLES:
        assert density < MIN_CHARS_PER_PAGE
        assert has_usable_text_layer(*_text_and_pages(pdf)) is False
    else:
        assert density > MIN_CHARS_PER_PAGE
        assert has_usable_text_layer(*_text_and_pages(pdf)) is True


def test_threshold_sits_in_an_empty_gap():
    digital, scanned = [], []
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        (scanned if pdf.name in SCANNED_SAMPLES else digital).append(_density(pdf))

    assert digital and scanned

    floor, ceiling = max(scanned), min(digital)

    assert floor < MIN_CHARS_PER_PAGE < ceiling

    assert MIN_CHARS_PER_PAGE >= floor + 100
    assert ceiling >= MIN_CHARS_PER_PAGE * 5


def test_has_usable_text_layer_boundary():
    exactly_at = "x" * MIN_CHARS_PER_PAGE
    one_short = "x" * (MIN_CHARS_PER_PAGE - 1)

    assert has_usable_text_layer(exactly_at, 1) is True
    assert has_usable_text_layer(one_short, 1) is False

    assert has_usable_text_layer(exactly_at * 2, 2) is True
    assert has_usable_text_layer(exactly_at + one_short, 2) is False

    assert has_usable_text_layer("   " + exactly_at + "  \n", 1) is True

    assert has_usable_text_layer(exactly_at, 0) is False
    assert has_usable_text_layer(exactly_at, -1) is False
