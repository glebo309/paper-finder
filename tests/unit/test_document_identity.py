"""Real, local PDF fixtures: no downloads or provider requests."""
from pathlib import Path

from PyPDF2 import PdfWriter
from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from src.core import validation


TARGET = {
    "title": "Highly accurate protein structure prediction with AlphaFold",
    "authors": ["John Jumper", "Richard Evans"],
    "doi": "10.1038/s41586-021-03819-2",
}


def pdf(tmp_path, text="", metadata=None):
    path = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    page = writer.pages[0]
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    lines = ["BT /F1 12 Tf 50 740 Td"]
    for line in text.splitlines():
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(f"({escaped}) Tj 0 -15 Td")
    lines.append("ET")
    stream.set_data("\n".join(lines).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if metadata:
        writer.add_metadata(metadata)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def verify(path, target=None):
    return validation.verify_document_identity(path, target or TARGET)


def test_title_wrapped_across_lines_is_verified_without_doi(tmp_path):
    result = verify(pdf(tmp_path, "Highly accurate protein structure\nprediction with AlphaFold\nJohn Jumper and Richard Evans\nAbstract\nWe present a new method."))
    assert result["status"] == "verified"
    assert result["reasons"]


def test_target_doi_in_references_does_not_verify_wrong_paper(tmp_path):
    result = verify(pdf(tmp_path, "A survey of molecular docking\nJane Smith\nAbstract\nThis survey discusses recent progress.\nReferences\nJumper. Highly accurate protein structure prediction with AlphaFold.\n10.1038/s41586-021-03819-2"))
    assert result["status"] == "mismatch"


def test_body_citation_does_not_verify_wrong_paper(tmp_path):
    result = verify(pdf(tmp_path, "Molecular docking in drug discovery\nJane Smith\nAbstract\nWe examine Highly accurate protein structure prediction with AlphaFold\nhttps://doi.org/10.1038/s41586-021-03819-2"))
    assert result["status"] == "mismatch"


def test_supplement_with_correct_title_and_doi_is_not_main_article(tmp_path):
    result = verify(pdf(tmp_path, "Supplementary Information\nHighly accurate protein structure prediction with AlphaFold\n10.1038/s41586-021-03819-2\nJohn Jumper"))
    assert result["status"] == "mismatch"
    assert any("supplement" in reason.lower() for reason in result["reasons"])


def test_blank_scan_is_unverifiable(tmp_path):
    assert verify(pdf(tmp_path))["status"] == "unverifiable"


def test_corrupt_pdf_is_unverifiable(tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"invalid" * 100)
    assert verify(path)["status"] == "unverifiable"


def test_doi_prefix_match_cannot_verify_other_doi(tmp_path):
    target = {"doi": "10.1000/123"}
    assert verify(pdf(tmp_path, "Research article\nDOI: 10.1000/1234\nAbstract\nNew results."), target)["status"] == "mismatch"


def test_doi_only_can_match_explicit_metadata(tmp_path):
    result = verify(pdf(tmp_path, metadata={"/doi": TARGET["doi"]}), {"doi": TARGET["doi"]})
    assert result["status"] == "verified"


def test_identifier_record_supports_arxiv_front_matter(tmp_path):
    record = {"identifier": {"type": "arxiv", "value": "1706.03762"}}
    result = verify(pdf(tmp_path, "Attention Is All You Need\nAshish Vaswani\narXiv:1706.03762v7 [cs.CL]\nAbstract\nNew architecture"), record)
    assert result["status"] == "verified"


def test_metadata_title_match_does_not_override_clear_wrong_page(tmp_path):
    result = verify(pdf(tmp_path, "A survey of molecular docking\nJane Smith\nAbstract\nSurvey results.", {"/Title": TARGET["title"]}))
    assert result["status"] != "verified"


def test_tiny_valid_pdf_can_be_verified(tmp_path):
    path = pdf(tmp_path, TARGET["title"] + "\nJohn Jumper\nAbstract\nResults")
    assert path.stat().st_size < 50 * 1024
    assert verify(path)["status"] == "verified"


def test_doi_wrapper_rejects_bibliography_match(tmp_path):
    path = pdf(tmp_path, "A different article\nReferences\n" + TARGET["doi"])
    assert validation.validate_pdf_contains_doi(path, TARGET["doi"]) is False


def test_metadata_wrapper_never_trusts_a_source_without_evidence(tmp_path):
    path = pdf(tmp_path, "A different article\nJane Smith\nAbstract\nDifferent results")
    assert validation.validate_pdf_matches_metadata(path, TARGET, TARGET["doi"], "sci-hub") is False


def test_no_target_identifiers_is_unverifiable(tmp_path):
    assert validation.verify_document_identity(pdf(tmp_path, "Some research paper"), {})["status"] == "unverifiable"


def test_readable_rejects_corrupt_magic_byte_only_file(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"x" * (60 * 1024))
    assert validation.check_pdf_readable(path) is False


def test_readable_accepts_small_structurally_valid_pdf(tmp_path):
    assert validation.check_pdf_readable(pdf(tmp_path, TARGET["title"])) is True


@pytest.mark.parametrize("heading", ["Supplementary Materials", "Supporting Information for:", "Supplementary Information for the article"])
def test_supplement_heading_variants_are_not_accepted(tmp_path, heading):
    result = verify(pdf(tmp_path, heading + "\n" + TARGET["title"] + "\nJohn Jumper\n" + TARGET["doi"]))
    assert result["status"] == "mismatch"


def test_mention_of_supplement_availability_does_not_reject_main_article(tmp_path):
    result = verify(pdf(tmp_path, TARGET["title"] + "\nJohn Jumper\nSupplementary information is available online.\nAbstract\nResults"))
    assert result["status"] == "verified"


def test_title_alone_cannot_override_missing_expected_authors(tmp_path):
    target = {"title": "A new method for protein structure prediction", "authors": ["Jane Smith"]}
    path = pdf(tmp_path, target["title"] + "\nJohn Jones and Sarah Miller\nAbstract\nA different paper with the same title.")
    assert verify(path, target)["status"] == "unverifiable"
