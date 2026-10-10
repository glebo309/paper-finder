"""Warm metadata searches avoid requests without concealing stale data or quotas."""
from unittest.mock import Mock

from src.core.discovery import DiscoveryService
from src.core.discovery_cache import DiscoveryCache
from src.core import provider_limits


TITLE = 'Highly accurate protein structure prediction with AlphaFold'
DOI = '10.1038/s41586-021-03819-2'


def response(title=TITLE, status=200):
    return Mock(status_code=status, headers={'Retry-After': '120'}, json=Mock(return_value={
        'message': {'items': [{'title': [title], 'DOI': DOI, 'author': [{'family': 'Jumper'}]}]}}))


def service(tmp_path, session, **kwargs):
    return DiscoveryService(session=session, providers=('crossref',), cache=DiscoveryCache(tmp_path, enabled=True), **kwargs)


def test_second_instance_reuses_response_and_reports_age(tmp_path):
    first = Mock(get=Mock(return_value=response()))
    initial = service(tmp_path, first).search(TITLE)
    assert first.get.call_count == 1
    second = Mock(get=Mock(side_effect=AssertionError('Warm cache must avoid HTTP')))
    repeated = service(tmp_path, second).search(TITLE)
    assert repeated['selected']['doi'] == initial['selected']['doi']
    assert repeated['cache']['hits']['crossref']['age_seconds'] >= 0
    assert repeated['cache']['hits']['crossref']['expires_at'] > 0
    assert not second.get.called


def test_refresh_bypasses_cache_and_updates_stored_metadata(tmp_path):
    service(tmp_path, Mock(get=Mock(return_value=response()))).search(TITLE)
    session = Mock(get=Mock(return_value=response(TITLE + ' corrected')))
    refreshed = service(tmp_path, session, refresh=True).search(TITLE)
    assert session.get.call_count == 1
    assert refreshed['cache']['hits'] == {}
    assert refreshed['candidates'][0]['title'].endswith('corrected')
    hit = service(tmp_path, Mock(get=Mock(side_effect=AssertionError()))).search(TITLE)
    assert hit['candidates'][0]['title'].endswith('corrected')


def test_cached_record_remains_usable_during_provider_cooldown(tmp_path):
    cache = DiscoveryCache(tmp_path, enabled=True)
    service(tmp_path, Mock(get=Mock(return_value=response()))).search(TITLE)
    cache.set_cooldown('crossref', 120)
    hit = service(tmp_path, Mock(get=Mock(side_effect=AssertionError()))).search(TITLE)
    assert hit['status'] == 'matched'
    assert hit['errors'] == {}


def test_refresh_still_honors_persistent_cooldown(tmp_path):
    cache = DiscoveryCache(tmp_path, enabled=True)
    cache.set_cooldown('crossref', 120)
    session = Mock(get=Mock(side_effect=AssertionError('Cooldown must prevent HTTP')))
    result = service(tmp_path, session, refresh=True).search(TITLE)
    assert result['errors']['crossref']['kind'] == 'rate_limited'
    assert not session.get.called


def test_429_survives_new_process_cooldown_state(tmp_path, monkeypatch):
    first = service(tmp_path, Mock(get=Mock(return_value=response(status=429)))).search(TITLE)
    assert first['errors']['crossref']['kind'] == 'rate_limited'
    monkeypatch.setattr('src.core.discovery.provider_cooldowns', provider_limits.ProviderCooldowns())
    session = Mock(get=Mock(side_effect=AssertionError('Persisted 429 must prevent HTTP')))
    second = service(tmp_path, session).search('different query')
    assert second['errors']['crossref']['kind'] == 'rate_limited'
    assert not session.get.called


def test_errors_are_retried_and_empty_results_do_not_hide_new_work(tmp_path):
    session = Mock(get=Mock(side_effect=[response(status=503),
        Mock(status_code=200, headers={}, json=Mock(return_value={'message': {'items': []}})), response()]))
    for _ in range(3):
        result = service(tmp_path, session).search(TITLE)
    assert session.get.call_count == 3
    assert result['selected']['doi'] == DOI


def test_semantic_cache_is_usable_during_process_throttle(tmp_path, monkeypatch):
    cache = DiscoveryCache(tmp_path, enabled=True)
    query = 'a description that needs semantic retrieval'
    rec = {'title': TITLE, 'identifier': {'type': 'doi', 'value': DOI}, 'doi': DOI,
           'authors': [], 'year': 2021, 'sources': ['openalex'], 'source_ranks': {'openalex_semantic': 1}}
    cache.put('openalex', query, 10, [dict(rec, source_ranks={'openalex': 1})])
    cache.put('openalex_semantic', query, 10, [rec])
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', float('inf'))
    result = DiscoveryService(session=Mock(get=Mock(side_effect=AssertionError())), providers=('openalex',), cache=cache).search(query)
    assert 'openalex_semantic' not in result['errors']
    assert 'openalex_semantic' in result['cache']['hits']
