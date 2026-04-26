import pytest

try:
    import responses
except ImportError:  # pragma: no cover - environment-dependent
    responses = None
    # Skip this whole module if `responses` is not available in the current interpreter
    pytest.skip("responses package is required for metadata tests", allow_module_level=True)

from src.core.metadata import MetadataResolver


def test_extract_doi_from_text_various_formats():
    resolver = MetadataResolver()

    # Bare DOI
    text1 = "This is a ref 10.1234/example.doi in the text."
    assert resolver.extract_doi_from_text(text1) == "10.1234/example.doi"

    # DOI URL
    text2 = "See https://doi.org/10.5678/another.doi for details."
    assert resolver.extract_doi_from_text(text2) == "10.5678/another.doi"

    # Prefixed DOI
    text3 = "DOI: 10.9999/prefix.doi)."
    assert resolver.extract_doi_from_text(text3) == "10.9999/prefix.doi"


@responses.activate
def test_get_crossref_metadata_success(valid_doi):
    """get_crossref_metadata() should return populated metadata on HTTP 200."""
    url = f"https://api.crossref.org/works/{valid_doi}"
    payload = {
        "message": {
            "DOI": valid_doi,
            "title": ["Test Title"],
            "author": [
                {"given": "Alice", "family": "Smith"},
                {"given": "Bob", "family": "Jones"},
            ],
            "published-print": {"date-parts": [[2023, 1, 1]]},
            "container-title": ["Journal of Testing"],
            "publisher": "Test Publisher",
            "ISBN": ["9780123456789"],
            "type": "journal-article",
        }
    }

    responses.add(
        responses.GET,
        url,
        status=200,
        json=payload,
        content_type="application/json",
    )

    resolver = MetadataResolver()
    meta = resolver.get_crossref_metadata(valid_doi)

    assert meta is not None
    assert meta["doi"] == valid_doi
    assert meta["title"] == "Test Title"
    assert meta["authors"] == ["Alice Smith", "Bob Jones"]
    assert meta["year"] == 2023
    assert meta["journal"] == "Journal of Testing"
    assert meta["publisher"] == "Test Publisher"
    assert meta["ISBN"] == "9780123456789"
    assert meta["type"] == "journal-article"


@responses.activate
def test_get_crossref_metadata_http_error(valid_doi):
    """get_crossref_metadata() should return None on non-200 responses."""
    url = f"https://api.crossref.org/works/{valid_doi}"
    responses.add(
        responses.GET,
        url,
        status=500,
        body="Internal Server Error",
        content_type="text/plain",
    )

    resolver = MetadataResolver()
    meta = resolver.get_crossref_metadata(valid_doi)
    assert meta is None


@responses.activate
def test_resolve_reference_uses_search_api(valid_doi):
    """resolve_reference() should use Crossref search API when no DOI in text."""
    search_url = "https://api.crossref.org/works"
    ref_str = "Some complex reference string without explicit DOI"

    payload = {
        "message": {
            "items": [
                {"DOI": valid_doi},
            ]
        }
    }

    responses.add(
        responses.GET,
        search_url,
        status=200,
        json=payload,
        content_type="application/json",
    )

    resolver = MetadataResolver()
    doi = resolver.resolve_reference(ref_str)
    assert doi == valid_doi


@responses.activate
def test_resolve_reference_handles_failure():
    """resolve_reference() should return None when the search API fails."""
    search_url = "https://api.crossref.org/works"
    ref_str = "Some complex reference that will fail"

    responses.add(
        responses.GET,
        search_url,
        status=500,
        body="Internal Server Error",
        content_type="text/plain",
    )

    resolver = MetadataResolver()
    doi = resolver.resolve_reference(ref_str)
    assert doi is None
