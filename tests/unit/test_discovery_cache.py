"""Persistent metadata caching is optional, bounded, and safe to discard."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.core.discovery_cache import DiscoveryCache


@pytest.fixture(autouse=True)
def enable_cache(monkeypatch):
    monkeypatch.setenv('PAPER_FINDER_CACHE', '1')


def record(title='A scholarly paper'):
    return {'title': title, 'identifier': {'type': 'doi', 'value': '10.1234/example'},
            'doi': '10.1234/example', 'authors': ['A. Researcher'], 'year': 2024,
            'sources': ['crossref'], 'pdf_urls': ['https://example.org/paper.pdf']}


def test_persists_across_instances_with_age_and_expiry(tmp_path):
    clock = [1000.0]
    first = DiscoveryCache(tmp_path, clock=lambda: clock[0], ttl_seconds=60)
    assert first.put('crossref', 'my query', 10, [record()])
    clock[0] += 12
    hit = DiscoveryCache(tmp_path, clock=lambda: clock[0]).get('crossref', 'my query', 10)
    assert hit['records'] == [record()]
    assert hit['age_seconds'] == 12
    assert hit['expires_at'] == 1060
    clock[0] = 1060
    assert first.get('crossref', 'my query', 10) is None


def test_keys_separate_provider_count_doi_and_case(tmp_path):
    cache = DiscoveryCache(tmp_path)
    assert cache.put('crossref', 'Case Query', 10, [record()], exact_doi='10.1/X')
    for provider, query, count, doi in [('openalex', 'Case Query', 10, '10.1/X'),
            ('crossref', 'case query', 10, '10.1/X'), ('crossref', 'Case Query', 20, '10.1/X'),
            ('crossref', 'Case Query', 10, None)]:
        assert cache.get(provider, query, count, exact_doi=doi) is None
    assert cache.get('crossref', ' Case   Query ', 10, exact_doi='10.1/X')


def test_empty_results_and_errors_are_not_cached(tmp_path):
    cache = DiscoveryCache(tmp_path)
    assert not cache.put('crossref', 'empty', 10, [])
    assert cache.get('crossref', 'empty', 10) is None
    for bad in ({'error': 'network'}, [{'error': 'rate limit'}], [{'title': 'Oops', 'error': 'failure'}], None):
        assert not cache.put('crossref', 'bad', 10, bad)
        assert cache.get('crossref', 'bad', 10) is None


def test_bounds_evict_oldest_and_reject_oversize(tmp_path):
    clock = [1000.0]
    cache = DiscoveryCache(tmp_path, max_entries=2, max_bytes=900, max_entry_bytes=600, clock=lambda: clock[0])
    for query in ['one', 'two', 'three']:
        assert cache.put('crossref', query, 10, [record()])
        clock[0] += 1
    assert cache.get('crossref', 'one', 10) is None
    assert cache.get('crossref', 'three', 10)
    assert not cache.put('crossref', 'huge', 10, [record('x' * 1000)])
    with sqlite3.connect(cache.path) as connection:
        count, size = connection.execute('SELECT COUNT(*), SUM(size) FROM responses').fetchone()
    assert count <= 2 and size <= 900


def test_byte_budget_evicts_even_below_entry_limit(tmp_path):
    cache = DiscoveryCache(tmp_path, max_entries=100, max_bytes=400)
    assert cache.put('crossref', 'one', 10, [record()])
    assert cache.put('crossref', 'two', 10, [record()])
    with sqlite3.connect(cache.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM responses').fetchone()[0] == 1


def test_corrupt_record_and_database_fail_open(tmp_path):
    cache = DiscoveryCache(tmp_path)
    cache.put('crossref', 'query', 10, [record()])
    with sqlite3.connect(cache.path) as connection:
        connection.execute("UPDATE responses SET payload='not json'")
    assert cache.get('crossref', 'query', 10) is None
    cache.path.write_bytes(b'not sqlite')
    assert cache.get('crossref', 'query', 10) is None
    assert not cache.put('crossref', 'query', 10, [record()])


def test_unwritable_or_invalid_location_never_breaks_search(tmp_path):
    invalid = tmp_path / 'file'
    invalid.write_text('not a directory')
    cache = DiscoveryCache(invalid)
    assert cache.get('crossref', 'query', 10) is None
    assert not cache.put('crossref', 'query', 10, [record()])
    assert cache.cooldown_remaining('crossref') == 0
    assert not cache.set_cooldown('crossref', 20)


def test_readonly_database_failure_is_nonfatal(tmp_path, monkeypatch):
    cache = DiscoveryCache(tmp_path)
    def deny(*args, **kwargs):
        raise sqlite3.OperationalError('attempt to write a readonly database')
    monkeypatch.setattr(sqlite3, 'connect', deny)
    assert not cache.put('crossref', 'query', 10, [record()])
    assert cache.get('crossref', 'query', 10) is None


def test_env_location_and_opt_out(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPER_FINDER_CACHE_DIR', str(tmp_path))
    cache = DiscoveryCache()
    assert cache.path.parent == tmp_path
    monkeypatch.setenv('PAPER_FINDER_CACHE', '0')
    disabled = DiscoveryCache(tmp_path / 'disabled')
    assert not disabled.put('crossref', 'query', 10, [record()])
    assert disabled.get('crossref', 'query', 10) is None
    assert not (tmp_path / 'disabled').exists()


def test_credentials_unknown_fields_and_secret_urls_are_not_persisted(tmp_path):
    cache = DiscoveryCache(tmp_path)
    value = record()
    value.update(api_key='SECRET', headers={'Authorization': 'SECRET'}, raw_response={'token': 'SECRET'},
                 url='https://example.org/paper?api_key=SECRET',
                 pdf_urls=['https://user:SECRET@example.org/file.pdf', 'https://example.org/file.pdf?token=SECRET'])
    assert cache.put('crossref', 'query with SECRET', 10, [value])
    restored = cache.get('crossref', 'query with SECRET', 10)['records'][0]
    assert 'api_key' not in restored and restored['pdf_urls'] == []
    assert restored['url'] == ''
    assert b'SECRET' not in cache.path.read_bytes()


def test_cooldowns_persist_and_cannot_be_shortened(tmp_path):
    clock = [1000.0]
    cache = DiscoveryCache(tmp_path, clock=lambda: clock[0])
    assert cache.set_cooldown('openalex_semantic', 120)
    clock[0] += 10
    second = DiscoveryCache(tmp_path, clock=lambda: clock[0])
    assert second.cooldown_remaining('openalex') == 110
    assert second.set_cooldown('openalex', 5)
    assert second.cooldown_remaining('openalex') == 110
    assert second.cooldown_remaining('crossref') == 0
    clock[0] = 1120
    assert second.cooldown_remaining('openalex') == 0
    assert not second.set_cooldown('openalex', float('inf'))


def test_concurrent_instances_do_not_corrupt_cache(tmp_path):
    def use(index):
        cache = DiscoveryCache(tmp_path)
        cache.put('crossref', str(index), 10, [record()])
        return cache.get('crossref', str(index), 10)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(use, range(20)))
    assert all(result is None or result['records'] == [record()] for result in results)
    cache = DiscoveryCache(tmp_path)
    assert cache.put('crossref', 'last', 10, [record()])
    assert cache.get('crossref', 'last', 10)


def test_indexed_version_evidence_survives_cache_without_credentials(tmp_path):
    cache = DiscoveryCache(tmp_path)
    value = record()
    evidence = {'pdf_url': 'https://repo.org/preprint.pdf', 'landing_page_url': 'https://repo.org/paper',
                'version': 'submittedVersion', 'is_oa': True, 'license': 'cc-by', 'source': 'openalex',
                'requires_selection': True, 'downloadable': False, 'version_conflict': True}
    value['indexed_locations'] = [dict(evidence, authorization='SECRET'),
        dict(evidence, pdf_url='https://repo.org/paper.pdf?token=SECRET', landing_page_url='https://user:SECRET@repo.org/paper')]
    assert cache.put('openalex', 'query', 10, [value])
    restored = cache.get('openalex', 'query', 10)['records'][0]['indexed_locations']
    assert restored[0] == evidence
    assert restored[1]['pdf_url'] is None and restored[1]['landing_page_url'] is None
    assert restored[1]['requires_selection'] is True
    assert restored[1]['downloadable'] is False
    assert b'SECRET' not in cache.path.read_bytes()


def test_pre_version_evidence_cache_entries_are_invalidated(tmp_path):
    import hashlib
    import json
    cache = DiscoveryCache(tmp_path)
    cache.put('openalex', 'query', 10, [record()])
    old_key = hashlib.sha256(json.dumps([1, 'openalex', 'query', 10, None],
                                      ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    with sqlite3.connect(cache.path) as connection:
        connection.execute('UPDATE responses SET key=?', (old_key,))
    assert cache.get('openalex', 'query', 10) is None
