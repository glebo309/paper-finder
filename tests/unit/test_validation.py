from pathlib import Path

import pytest

from src.core.validation import (
    validate_pdf,
    is_pdf_content,
    check_pdf_readable,
)
import src.core.validation as validation_mod


def _write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(data)


def test_validate_pdf_accepts_valid_pdf(tmp_path):
    """validate_pdf() should return True for a valid PDF file."""
    pdf_bytes = b"%PDF-1.4\n" + b"x" * 2048
    pdf_path = tmp_path / "valid.pdf"
    _write_bytes(pdf_path, pdf_bytes)

    assert validate_pdf(pdf_path, min_size_kb=1) is True


def test_validate_pdf_rejects_html_disguised_as_pdf(tmp_path):
    """validate_pdf() should reject HTML disguised as PDF."""
    pdf_html = b"%PDF-1.4\n<html><body>error page</body></html>"
    pdf_path = tmp_path / "html_disguised.pdf"
    _write_bytes(pdf_path, pdf_html)

    assert validate_pdf(pdf_path, min_size_kb=0) is False


def test_is_pdf_content_valid():
    """is_pdf_content() returns True for valid PDF-like bytes."""
    content = b"%PDF-1.7\n" + b"x" * 2048
    assert is_pdf_content(content, min_size_kb=1) is True


def test_is_pdf_content_too_small():
    """is_pdf_content() returns False when content is too small."""
    content = b"%PDF-1.4\n" + b"x" * 10
    assert is_pdf_content(content, min_size_kb=1) is False


def test_is_pdf_content_rejects_html():
    """is_pdf_content() returns False when HTML markers are present."""
    content = b"%PDF-1.4\n<html>error</html>" + b"x" * 2048
    assert is_pdf_content(content, min_size_kb=0) is False


def test_check_pdf_readable_valid(tmp_path):
    """check_pdf_readable() should return True for a valid PDF file."""
    # Must be larger than the default 50KB threshold used by validate_pdf()
    pdf_bytes = b"%PDF-1.4\n" + b"x" * (60 * 1024)
    pdf_path = tmp_path / "valid_readable.pdf"
    _write_bytes(pdf_path, pdf_bytes)

    assert check_pdf_readable(pdf_path) is True


def test_check_pdf_readable_invalid(tmp_path):
    """check_pdf_readable() should return False when validate_pdf() fails."""
    bad_bytes = b"NOT_A_PDF" + b"x" * 2048
    pdf_path = tmp_path / "invalid_readable.pdf"
    _write_bytes(pdf_path, bad_bytes)

    assert check_pdf_readable(pdf_path) is False


# Optional title-matching tests - skipped if is_valid_title() is not present

HAS_IS_VALID_TITLE = hasattr(validation_mod, "is_valid_title")


@pytest.mark.skipif(
    not HAS_IS_VALID_TITLE, reason="is_valid_title() not implemented in validation.py",
)
def test_is_valid_title_success():
    title = "Emergent properties of biological signaling networks"
    candidate = "Emergent properties of biological signaling networks in cells"
    assert validation_mod.is_valid_title(title, candidate) is True


@pytest.mark.skipif(
    not HAS_IS_VALID_TITLE, reason="is_valid_title() not implemented in validation.py",
)
def test_is_valid_title_access_denied():
    title = "Emergent properties of biological signaling networks"
    candidate = "Access denied or paywalled content"
    assert validation_mod.is_valid_title(title, candidate) is False
