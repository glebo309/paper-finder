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


def test_conflicting_arxiv_id_cannot_be_overridden_by_title_and_authors(tmp_path):
    record = {'identifier': {'type': 'arxiv', 'value': '1706.03762'},
              'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani']}
    path = pdf(tmp_path, record['title'] + '\nAshish Vaswani\narXiv:9999.12345v1\nAbstract\nResults')
    assert verify(path, record)['status'] == 'mismatch'


@pytest.mark.parametrize('requested, found, expected', [
    ('1706.03762v2', '1706.03762v3', 'mismatch'),
    ('1706.03762v2', '1706.03762v2', 'verified'),
    ('1706.03762', '1706.03762v3', 'verified'),
    ('1706.03762v2', '1706.03762', 'unverifiable'),
])
def test_explicit_arxiv_version_is_part_of_selected_identity(tmp_path, requested, found, expected):
    record = {'identifier': {'type': 'arxiv', 'value': requested},
              'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani']}
    path = pdf(tmp_path, record['title'] + '\nAshish Vaswani\narXiv:' + found + '\nAbstract\nResults')
    assert verify(path, record)['status'] == expected


def test_balanced_doi_parenthesis_is_significant(tmp_path):
    path = pdf(tmp_path, 'Research Article\nDOI: 10.1000/example(a)\nAbstract\nDetails')
    assert verify(path, {'doi': '10.1000/example(a'})['status'] == 'mismatch'
    assert verify(path, {'doi': '10.1000/example(a)'})['status'] == 'verified'


def test_doi_parenthetical_wrapping_is_not_part_of_identifier(tmp_path):
    path = pdf(tmp_path, 'Research Article\n(DOI: 10.1000/example(a)).\nAbstract\nDetails')
    result = verify(path, {'doi': '10.1000/example(a)'})
    assert result['status'] == 'verified'
    assert result['front_matter_dois'] == ['10.1000/example(a)']


def test_arxiv_margin_stamp_verifies_explicit_version_after_abstract(tmp_path):
    record = {'identifier': {'type': 'arxiv', 'value': '1706.03762v7'},
              'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani']}
    path = pdf(tmp_path, record['title'] + '\nAshish Vaswani\nAbstract\nOur findings.\n'
               'Conference proceedings.arXiv:1706.03762v7  [cs.CL]  2 Aug 2023')
    assert verify(path, record)['status'] == 'verified'


def test_arxiv_citation_in_abstract_does_not_confirm_requested_version(tmp_path):
    record = {'identifier': {'type': 'arxiv', 'value': '1706.03762v7'},
              'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani']}
    path = pdf(tmp_path, record['title'] + '\nAshish Vaswani\nAbstract\n'
               'We discuss arXiv:1706.03762v7 among related papers.')
    assert verify(path, record)['status'] == 'unverifiable'


def test_legacy_doi_angle_brackets_are_significant(tmp_path):
    doi = '10.1002/(SICI)1099-0844(199912)17:4<290::AID-CBF849>3.0.CO;2-1'
    path = pdf(tmp_path, 'Research Article\nDOI: ' + doi + '\nAbstract\nResults')
    result = verify(path, {'doi': doi})
    assert result['status'] == 'verified'
    assert result['front_matter_dois'] == [doi.lower()]


def test_doi_angle_suffix_is_not_stripped_to_match_another_identifier(tmp_path):
    path = pdf(tmp_path, 'Research Article\nDOI: 10.1000/example<component>\nAbstract\nResults')
    assert verify(path, {'doi': '10.1000/example'})['status'] == 'mismatch'


def test_angle_wrapped_doi_preserves_internal_balanced_brackets(tmp_path):
    path = pdf(tmp_path, 'Research Article\n<10.1000/example<component>>\nAbstract\nResults')
    result = verify(path, {'doi': '10.1000/example<component>'})
    assert result['status'] == 'verified'
    assert result['front_matter_dois'] == ['10.1000/example<component>']


SPACED_TARGET = {'title': 'Thiamine Diphosphate-Dependent Biocatalysis in the 21<sup>st</sup> Century',
                 'doi': '10.1002/chem.71699', 'authors': ['Lucrezia Lanza', 'Daniela Bjarnesen', 'Michael Muller']}
GLUED_HEADING = 'ThiamineDiphosphate-DependentBiocatalysisinthe21st\nCentury'


def test_glued_title_verified_with_explicit_wiley_article_doi(tmp_path):
    path = pdf(tmp_path, 'Chemistry A European Journal\nPERSPECTIVE\n' + GLUED_HEADING +
               '\nLucreziaLanza DanielaBjarnesen MichaelMuller\nAbstract\nResults',
               {'/Title': 'Thiamine Diphosphate-Dependent Biocatalysis in the 21st Century',
                '/WPS-ARTICLEDOI': SPACED_TARGET['doi']})
    result = verify(path, SPACED_TARGET)
    assert result['status'] == 'verified'
    assert result['compact_title_match'] is True
    assert result['identifier_match'] is True


def test_glued_title_requires_full_author_when_no_identifier(tmp_path):
    path = pdf(tmp_path, GLUED_HEADING + '\nLucreziaLanza\nAbstract\nResults')
    result = verify(path, SPACED_TARGET)
    assert result['status'] == 'verified'
    assert 'lanza' in result['matched_authors']


def test_glued_title_without_independent_corroboration_is_not_verified(tmp_path):
    path = pdf(tmp_path, GLUED_HEADING + '\nSomeoneElse\nAbstract\nResults')
    assert verify(path, SPACED_TARGET)['status'] != 'verified'


def test_article_doi_and_metadata_title_do_not_override_wrong_heading(tmp_path):
    path = pdf(tmp_path, 'An unrelated enzymatic pathway survey\nJane Smith\nAbstract\nResults',
               {'/Title': SPACED_TARGET['title'], '/WPS-ARTICLEDOI': SPACED_TARGET['doi']})
    assert verify(path, SPACED_TARGET)['status'] != 'verified'


@pytest.mark.parametrize('heading', ['SupportingInformation', 'SupplementaryInformation', 'SupplementaryMaterials'])
def test_glued_supplement_heading_is_still_rejected(tmp_path, heading):
    path = pdf(tmp_path, heading + '\n' + GLUED_HEADING + '\nLucreziaLanza\nAbstract\nDetails',
               {'/WPS-ARTICLEDOI': SPACED_TARGET['doi']})
    result = verify(path, SPACED_TARGET)
    assert result['status'] == 'mismatch'
    assert 'supplement' in result['reasons'][0].lower()


def test_compact_title_in_body_is_not_title_evidence(tmp_path):
    path = pdf(tmp_path, 'A different paper on enzymatic mechanisms\nJane Smith\nAbstract\n' +
               GLUED_HEADING + '\nLucreziaLanza', {'/WPS-ARTICLEDOI': SPACED_TARGET['doi']})
    assert verify(path, SPACED_TARGET)['status'] != 'verified'


def test_journal_doi_metadata_cannot_identify_article(tmp_path):
    path = pdf(tmp_path, GLUED_HEADING + '\nUnknown Authors\nAbstract\nResults',
               {'/WPS-JOURNALDOI': SPACED_TARGET['doi']})
    assert verify(path, SPACED_TARGET)['status'] != 'verified'


def test_expected_article_doi_metadata_cannot_override_conflicting_page_doi(tmp_path):
    path = pdf(tmp_path, GLUED_HEADING + '\nLucreziaLanza\nDOI: 10.1002/chem.different\nAbstract\nResults',
               {'/WPS-ARTICLEDOI': SPACED_TARGET['doi']})
    assert verify(path, SPACED_TARGET)['status'] == 'mismatch'
