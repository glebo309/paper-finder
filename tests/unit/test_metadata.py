"""Offline metadata contracts using only stdlib mocks.

Free text must use shared discovery and return a DOI only for a confident match.
A provider's first search hit is never accepted merely because it contains a DOI.
"""
from unittest.mock import Mock

import pytest
import requests

from src.core.metadata import MetadataResolver


def session_with(payload=None, status=200):
    response = Mock(status_code=status)
    response.json.return_value = payload
    session = Mock(headers={})
    session.get.return_value = response
    return session


@pytest.mark.parametrize('reference, expected', [
    ('This is a ref 10.1234/example.doi in the text.', '10.1234/example.doi'),
    ('See https://doi.org/10.5678/another.doi for details.', '10.5678/another.doi'),
    ('DOI: 10.9999/prefix.doi).', '10.9999/prefix.doi'),
    ('No persistent identifier here', None),
    ('', None),
])
def test_extract_doi_from_text_various_formats(reference, expected):
    resolver = MetadataResolver(session=session_with())
    assert resolver.extract_doi_from_text(reference) == expected
    resolver.session.get.assert_not_called()


def test_get_crossref_metadata_success(valid_doi):
    payload = {'message': {
        'DOI': valid_doi, 'title': ['Test Title'],
        'author': [{'given': 'Alice', 'family': 'Smith'}, {'given': 'Bob', 'family': 'Jones'}],
        'published-print': {'date-parts': [[2023, 1, 1]]},
        'container-title': ['Journal of Testing'], 'publisher': 'Test Publisher',
        'ISBN': ['9780123456789'], 'type': 'journal-article',
    }}
    session = session_with(payload)
    meta = MetadataResolver(session=session).get_crossref_metadata(valid_doi)
    assert meta is not None
    assert meta['doi'] == valid_doi
    assert meta['title'] == 'Test Title'
    assert meta['authors'] == ['Alice Smith', 'Bob Jones']
    assert meta['year'] == 2023
    assert meta['journal'] == 'Journal of Testing'
    assert meta['publisher'] == 'Test Publisher'
    assert meta['ISBN'] == '9780123456789'
    assert meta['type'] == 'journal-article'
    session.get.assert_called_once_with(f'https://api.crossref.org/works/{valid_doi}', timeout=15)


@pytest.mark.parametrize('status', [404, 429, 500])
def test_get_crossref_metadata_http_error(valid_doi, status):
    session = session_with(status=status)
    assert MetadataResolver(session=session).get_crossref_metadata(valid_doi) is None
    session.get.return_value.json.assert_not_called()


def test_get_crossref_metadata_network_error(valid_doi, capsys):
    session = session_with()
    session.get.side_effect = requests.ConnectionError('SECRET_TOKEN must not appear')
    assert MetadataResolver(session=session).get_crossref_metadata(valid_doi) is None
    assert 'SECRET_TOKEN' not in capsys.readouterr().out


def test_get_crossref_metadata_malformed_json(valid_doi):
    session = session_with()
    session.get.return_value.json.side_effect = ValueError('not json')
    assert MetadataResolver(session=session).get_crossref_metadata(valid_doi) is None


def test_resolve_reference_returns_only_selected_doi(monkeypatch, valid_doi):
    session = session_with()
    selected = {'doi': valid_doi, 'title': 'A confirmed title'}
    search = Mock(return_value={'status': 'matched', 'selected': selected,
                                'candidates': [{'doi': '10.1234/wrong'}, selected], 'errors': {}})
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', search)
    assert MetadataResolver(session=session).resolve_reference('A confirmed title') == valid_doi
    search.assert_called_once_with('A confirmed title', mode='identify')
    session.get.assert_not_called()


@pytest.mark.parametrize('status', ['ambiguous', 'not_found', 'unavailable'])
def test_resolve_reference_rejects_unconfirmed_first_hit(monkeypatch, status):
    search = Mock(return_value={'status': status, 'selected': None,
                               'candidates': [{'doi': '10.1234/wrong'}], 'errors': {}})
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', search)
    assert MetadataResolver(session=session_with()).resolve_reference('a vague recollection') is None
    search.assert_called_once_with('a vague recollection', mode='identify')


def test_resolve_reference_preserves_no_doi_result_without_fabrication(monkeypatch):
    search = Mock(return_value={'status': 'matched', 'selected': {'title': 'Real paper',
                  'identifier': {'type': 'arxiv', 'value': '1706.03762'}}, 'candidates': [], 'errors': {}})
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', search)
    assert MetadataResolver(session=session_with()).resolve_reference('Real paper') is None


def test_doi_extraction_preserves_balanced_parentheses_and_supplement_suffix():
    resolver = MetadataResolver(session=session_with())
    assert resolver.extract_doi_from_text('doi: 10.1002/example(2021).') == '10.1002/example(2021)'
    assert resolver.extract_doi_from_text('https://doi.org/10.1234/PAPER.s001?ref=test#section') == '10.1234/paper.s001'


def test_wrong_crossref_identity_is_rejected(valid_doi):
    session = session_with({'message': {'DOI': '10.1234/something-else', 'title': ['Wrong paper']}})
    assert MetadataResolver(session=session).get_crossref_metadata(valid_doi) is None


def test_crossref_identity_is_normalized_before_comparing():
    session = session_with({'message': {'DOI': 'https://doi.org/10.1234/EXAMPLE', 'title': ['Real paper']}})
    result = MetadataResolver(session=session).get_crossref_metadata('10.1234/Example')
    assert result['doi'] == '10.1234/example'


def test_crossref_missing_doi_uses_exact_endpoint_identity(valid_doi):
    session = session_with({'message': {'title': ['Real paper']}})
    result = MetadataResolver(session=session).get_crossref_metadata(valid_doi)
    assert result['doi'] == valid_doi


def test_malformed_explicit_response_doi_is_not_silently_replaced(valid_doi):
    session = session_with({'message': {'DOI': 'invalid-id', 'title': ['Wrong paper']}})
    assert MetadataResolver(session=session).get_crossref_metadata(valid_doi) is None
