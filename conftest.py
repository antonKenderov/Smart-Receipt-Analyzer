from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"


def _build_pdf(objects: list[bytes], trailer_extra: bytes = b"") -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R" % (len(objects) + 1)
    out += trailer_extra + b" >>\n"
    out += b"startxref\n%d\n" % xref
    out += b"%%EOF\n"
    return bytes(out)


@pytest.fixture(scope="session")
def digital_pdf() -> Path:
    return SAMPLES / "7.pdf"


@pytest.fixture(scope="session")
def scanned_pdf() -> Path:
    return SAMPLES / "7_scanned.pdf"


@pytest.fixture
def encrypted_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "encrypted.pdf"
    path.write_bytes(
        _build_pdf(
            [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
                b"<< /Filter /Standard /V 1 /R 2 /P -1 "
                b"/O <" + b"AB" * 16 + b"> /U <" + b"CD" * 16 + b"> >>",
            ],
            trailer_extra=(
                b" /Encrypt 4 0 R /ID [<" + b"11" * 16 + b"> <" + b"22" * 16 + b">]"
            ),
        )
    )
    return path


@pytest.fixture
def blank_pdf(tmp_path: Path):
    def _make(pages: int, name: str | None = None) -> Path:
        path = tmp_path / (name or f"blank_{pages}.pdf")
        sheets = [Image.new("RGB", (612, 792), "white") for _ in range(pages)]
        sheets[0].save(path, "PDF", save_all=True, append_images=sheets[1:])
        return path

    return _make


@pytest.fixture
def bbox():
    def _make(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    return _make
