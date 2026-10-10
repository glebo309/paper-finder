from unittest.mock import Mock
import pytest
from src.core.identity import IdentityResolver
from src.core.metadata import MetadataResolver
from paper_finder import PaperFinder


def test_doi_metadata_can_come_from_any_index(monkeypatch):
    record = {'identifier': {'type': 'doi', 'value': '10.5281/zenodo.123'}, 'doi': '10.5281/zenodo.123', 'title': 'A research record', 'metadata_source': 'openalex'}
    search = Mock(return_value={'status': 'matched', 'selected': record, 'candidates': [record], 'errors': {}})
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', search)
    assert IdentityResolver().resolve(record['doi']) == record
    search.assert_called_once()


def test_doi_outage_remains_unavailable(monkeypatch):
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', lambda *a, **k: {'status': 'unavailable', 'selected': None, 'candidates': [], 'errors': {'openalex': {'kind': 'network_error'}}})
    record = IdentityResolver().resolve('10.1234/missing')
    assert record['status'] == 'unavailable'
    assert record['input_doi'] == '10.1234/missing'


def test_doi_parentheses_and_supplement_identity_are_preserved():
    resolver = IdentityResolver()
    assert resolver._extract_doi('doi:10.1002/(sici)123(abc).') == '10.1002/(sici)123(abc)'
    assert resolver._extract_doi('10.1021/test.s001') == '10.1021/test.s001'


@pytest.mark.parametrize('target', ['metadata', 'finder'])
def test_legacy_resolution_uses_same_uncertainty_policy(monkeypatch, target):
    search = Mock(return_value={'status': 'ambiguous', 'selected': None, 'candidates': [{'doi': '10.1234/wrong'}], 'errors': {}})
    monkeypatch.setattr('src.core.discovery.DiscoveryService.search', search)
    if target == 'metadata':
        resolver = MetadataResolver()
        assert resolver.resolve_reference('vague recollection') is None
    else:
        resolver = PaperFinder.__new__(PaperFinder)
        resolver.session = Mock()
        assert resolver._resolve_via_crossref('vague recollection') is None
    search.assert_called_once()
