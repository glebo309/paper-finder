"""Independent full-text source jobs for concurrent acquisition."""
from unittest.mock import Mock
import pytest

from src.acquisition.recent_open_access import RecentOpenAccessDiscovery, _location

DOI = '10.1234/example'


@pytest.mark.parametrize('provider,data,host', [
    ('europepmc', {'resultList': {'result': []}}, 'europepmc'),
    ('openalex', {'doi': DOI, 'locations': []}, 'openalex.org'),
    ('unpaywall', {'doi': DOI, 'oa_locations': []}, 'unpaywall.org'),
])
def test_explicit_index_job_never_calls_other_index_or_publisher(monkeypatch, provider, data, host):
    publisher = Mock()
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    response = Mock(status_code=200, headers={})
    response.json.return_value = data
    session = Mock()
    session.get.return_value = response
    cache = Mock()
    cache.cooldown_remaining.return_value = 0
    service = RecentOpenAccessDiscovery(session=session, cache=cache, providers=[provider],
                                       email='reader@example.edu', publisher_fallback=False)
    result = service.discover(DOI)
    assert result['status'] == 'not_found'
    assert session.get.call_count == 1 and host in session.get.call_args.args[0]
    publisher.assert_not_called()


def test_explicit_publisher_job_runs_with_fallback_disabled_and_no_indexes(monkeypatch):
    item = _location('publisher', DOI, pdf='https://journal.test/article.pdf', version='publishedVersion')
    publisher = Mock(return_value={'status': 'found', 'locations': [item], 'errors': {}})
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    session = Mock()
    result = RecentOpenAccessDiscovery(session=session, providers=['publisher'], publisher_fallback=False).discover(DOI)
    session.get.assert_not_called()
    publisher.assert_called_once()
    assert result['locations'] == [item] and result['status'] == 'found'


def test_explicit_publisher_not_suppressed_by_successful_index_and_runs_once(monkeypatch):
    item = _location('publisher', DOI, pdf='https://journal.test/article.pdf')
    publisher = Mock(return_value={'status': 'found', 'locations': [item]})
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    service = RecentOpenAccessDiscovery(providers=['openalex', 'publisher'], publisher_fallback=True)
    service._request = Mock(return_value=({'doi': DOI, 'locations': [
        {'is_oa': True, 'pdf_url': 'https://repository.test/paper.pdf'}]}, None))
    result = service.discover(DOI)
    assert len(result['locations']) == 2
    assert service._request.call_count == 1
    publisher.assert_called_once()


def test_default_preserves_conditional_publisher_fallback(monkeypatch):
    publisher = Mock()
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    service = RecentOpenAccessDiscovery()
    service._request = Mock(side_effect=[
        ({'resultList': {'result': []}}, None),
        ({'doi': DOI, 'oa_locations': [{'url_for_pdf': 'https://repository.test/paper.pdf'}]}, None),
        ({'doi': DOI, 'locations': []}, None),
    ])
    service.discover(DOI)
    assert [call.args[0] for call in service._request.call_args_list] == ['europepmc', 'unpaywall', 'openalex']
    publisher.assert_not_called()


def test_explicit_publisher_still_respects_overall_deadline(monkeypatch):
    publisher = Mock()
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    instants = iter([0, 2])
    monkeypatch.setattr('src.acquisition.recent_open_access.time.monotonic', lambda: next(instants))
    service = RecentOpenAccessDiscovery(providers=['publisher'], deadline=1)
    result = service.discover(DOI)
    assert result['errors']['publisher']['kind'] == 'deadline'
    publisher.assert_not_called()
