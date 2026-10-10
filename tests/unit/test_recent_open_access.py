"""Recent full-text discovery keeps versions and access evidence separate."""
from unittest.mock import Mock

import pytest
import requests

from src.acquisition.recent_open_access import RecentOpenAccessDiscovery
from src.core import provider_limits

DOI = '10.1234/recent.2026'


def response(data=None, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = data
    return result


def service(data, provider, **kwargs):
    # These tests isolate index behavior; publisher fallback has its own suite.
    kwargs.setdefault("publisher_fallback", False)
    session = Mock()
    session.get.return_value = response(data)
    return RecentOpenAccessDiscovery(session=session, providers=[provider], **kwargs), session


def test_unpaywall_all_versions_and_embargoes_without_silent_preprint_substitution():
    client, session = service({'doi': DOI, 'is_oa': True, 'oa_locations': [
        {'url_for_pdf': 'https://journal.org/article.pdf', 'version': 'publishedVersion', 'license': 'cc-by', 'host_type': 'publisher'},
        {'url_for_pdf': 'https://repo.edu/accepted.pdf', 'version': 'acceptedVersion', 'host_type': 'repository'},
        {'url_for_pdf': 'https://preprints.org/submitted.pdf', 'version': 'submittedVersion', 'host_type': 'repository'},
    ], 'oa_locations_embargoed': [
        {'url_for_landing_page': 'https://repo.edu/embargo', 'version': 'acceptedVersion', 'oa_date': '2027-01-01'},
    ]}, 'unpaywall', email='researcher@example.edu')
    result = client.discover(DOI)
    assert [x['version'] for x in result['locations']] == ['publishedVersion', 'acceptedVersion']
    assert result['locations'][0]['license'] == 'cc-by'
    assert result['locations'][0]['provenance'][0]['provider'] == 'unpaywall'
    assert result['alternatives'][0]['requires_selection'] is True
    assert result['alternatives'][0]['version'] == 'submittedVersion'
    assert result['embargoed'][0]['available_from'] == '2027-01-01'
    assert result['embargoed'][0]['downloadable'] is False
    assert result['status'] == 'found'
    assert session.get.call_args.kwargs['params']['email'] == 'researcher@example.edu'
    session.get.return_value.close.assert_called_once()


def test_unpaywall_requires_real_configured_contact(monkeypatch):
    monkeypatch.delenv('UNPAYWALL_EMAIL', raising=False)
    for email in (None, 'test@test.com', 'bad-email'):
        client, session = service({}, 'unpaywall', email=email)
        result = client.discover(DOI)
        session.get.assert_not_called()
        assert result['errors']['unpaywall']['kind'] == 'not_configured'


def test_openalex_preserves_all_open_locations_and_closed_landing():
    client, session = service({'doi': 'https://doi.org/' + DOI, 'locations': [
        {'is_oa': False, 'pdf_url': 'https://publisher.org/paywall.pdf', 'landing_page_url': 'https://publisher.org/article', 'version': 'publishedVersion'},
        {'is_oa': True, 'pdf_url': 'https://repo.edu/a.pdf', 'version': 'acceptedVersion', 'license': 'cc-by-nc', 'source': {'display_name': 'University', 'type': 'repository'}},
        {'is_oa': True, 'landing_page_url': 'https://repo.edu/record', 'version': None},
    ]}, 'openalex')
    result = client.discover(DOI)
    assert len(result['locations']) == 2
    assert result['locations'][0]['pdf_url'] == 'https://repo.edu/a.pdf'
    assert result['locations'][0]['host_type'] == 'repository'
    assert result['locations'][1]['downloadable'] is False
    assert result['locations'][1]['version'] == 'unknown'
    assert result['closed'][0]['landing_page_url'] == 'https://publisher.org/article'
    assert result['closed'][0]['downloadable'] is False
    assert session.get.call_count == 1


def test_europepmc_requires_exact_doi_and_free_links_and_keeps_preprint_separate():
    client, _ = service({'resultList': {'result': [
        {'doi': '10.1234/wrong', 'fullTextUrlList': {'fullTextUrl': [{'url': 'https://bad.org/wrong.pdf', 'documentStyle': 'pdf', 'availabilityCode': 'OA'}]}},
        {'doi': DOI, 'source': 'MED', 'fullTextUrlList': {'fullTextUrl': [
            {'url': 'https://publisher.org/full.pdf', 'documentStyle': 'pdf', 'availabilityCode': 'OA', 'site': 'Publisher'},
            {'url': 'https://publisher.org/paid.pdf', 'documentStyle': 'pdf', 'availabilityCode': 'S'},
            {'url': 'https://repo.edu/html', 'documentStyle': 'html', 'availabilityCode': 'F'},
        ]}},
        {'doi': DOI, 'source': 'PPR', 'fullTextUrlList': {'fullTextUrl': [
            {'url': 'https://preprints.org/file.pdf', 'documentStyle': 'pdf', 'availabilityCode': 'OA'},
        ]}},
    ]}}, 'europepmc')
    result = client.discover(DOI)
    assert [x['url'] for x in result['locations']] == ['https://publisher.org/full.pdf', 'https://repo.edu/html']
    assert result['locations'][0]['version'] == 'unknown'  # MED does not guarantee which version a link hosts.
    assert result['alternatives'][0]['version'] == 'submittedVersion'
    assert all('wrong.pdf' not in x['url'] for x in result['closed'])


def test_europepmc_never_invents_pmc_pdf_when_only_identifier_is_known():
    client, _ = service({'resultList': {'result': [{'doi': DOI, 'pmcid': 'PMC123456', 'isOpenAccess': 'N'}]}}, 'europepmc')
    result = client.discover(DOI)
    assert not result['locations']


@pytest.mark.parametrize('provider,data', [
    ('unpaywall', {'doi': '10.1234/another', 'oa_locations': [{'url_for_pdf': 'https://wrong.org/file.pdf'}]}),
    ('openalex', {'doi': 'https://doi.org/10.1234/another', 'locations': [{'is_oa': True, 'pdf_url': 'https://wrong.org/file.pdf'}]}),
])
def test_wrong_doi_response_rejected(provider, data):
    client, _ = service(data, provider, email='researcher@example.edu')
    result = client.discover(DOI)
    assert result['locations'] == []
    assert result['errors'][provider]['kind'] == 'identity_mismatch'


def test_deduplicates_urls_merges_provenance_and_keeps_version_conflicts_for_selection():
    session = Mock()
    session.get.side_effect = [
        response({'doi': DOI, 'oa_locations': [{'url_for_pdf': 'https://repo.org/full.pdf', 'version': 'acceptedVersion'}]}),
        response({'doi': DOI, 'locations': [{'is_oa': True, 'pdf_url': 'https://repo.org/full.pdf', 'version': 'submittedVersion'}]}),
    ]
    result = RecentOpenAccessDiscovery(session=session, providers=['unpaywall', 'openalex'], publisher_fallback=False, email='researcher@example.edu').discover(DOI)
    assert not result['locations']
    assert len(result['alternatives']) == 1
    assert result['alternatives'][0]['sources'] == ['unpaywall', 'openalex']
    assert result['alternatives'][0]['version'] == 'conflicting'
    assert len(result['alternatives'][0]['provenance']) == 2


def test_rate_limit_is_shared_and_not_retried():
    client, session = service({}, 'openalex')
    session.get.return_value = response(status=429, headers={'Retry-After': '3600'})
    first = client.discover(DOI)
    second = client.discover(DOI)
    assert first['errors']['openalex']['kind'] == 'rate_limited'
    assert second['errors']['openalex']['kind'] == 'rate_limited'
    assert provider_limits.remaining('openalex_semantic') > 3500
    assert session.get.call_count == 1


def test_shared_total_budget_stops_next_request(monkeypatch):
    from src.acquisition import recent_open_access
    now = [100.0]
    monkeypatch.setattr(recent_open_access.time, 'monotonic', lambda: now[0])
    session = Mock()
    def fetch(*args, **kwargs):
        assert kwargs['timeout'] <= 1
        now[0] += 2
        return response({'resultList': {'result': []}})
    session.get.side_effect = fetch
    result = RecentOpenAccessDiscovery(session=session, providers=['europepmc', 'openalex'], publisher_fallback=False, deadline=1).discover(DOI)
    assert session.get.call_count == 1
    assert result['errors']['openalex']['kind'] == 'deadline'


@pytest.mark.parametrize('bad_url', ['file:///tmp/a.pdf', 'javascript:alert(1)', 'https://user:password@host.org/a.pdf'])
def test_unsafe_location_urls_discarded(bad_url):
    client, _ = service({'doi': DOI, 'locations': [{'is_oa': True, 'pdf_url': bad_url}]}, 'openalex')
    assert not client.discover(DOI)['locations']


def test_timeout_does_not_prevent_independent_provider():
    session = Mock()
    session.get.side_effect = [requests.Timeout('secret-url'), response({'doi': DOI, 'locations': [{'is_oa': True, 'pdf_url': 'https://repo.org/full.pdf'}]})]
    result = RecentOpenAccessDiscovery(session=session, providers=['europepmc', 'openalex'], publisher_fallback=False).discover(DOI)
    assert result['locations']
    assert result['errors']['europepmc']['kind'] == 'timeout'
    assert 'secret-url' not in str(result)


@pytest.mark.parametrize('doi', ['', 'not a doi', '10.1234/foo" OR *', '10.1234/foo\nbar'])
def test_invalid_doi_does_not_call_providers(doi):
    client, session = service({}, 'openalex')
    assert client.discover(doi)['status'] == 'invalid'
    session.get.assert_not_called()


def test_explicit_opaque_legacy_doi_keeps_balanced_angle_brackets():
    doi = '10.1002/(SICI)1099-0690(199901)1999:1<1::AID-EJOC1>3.0.CO;2-1'
    client, session = service({'doi': doi, 'locations': []}, 'openalex')
    result = client.discover(doi)
    assert result['doi'] == doi.lower()
    assert session.get.call_count == 1
    assert '%3C' in session.get.call_args.args[0]
    assert '%3E' in session.get.call_args.args[0]


def test_percent_encoded_doi_url_resolves_without_tracking_query():
    client, session = service({'doi': DOI, 'locations': []}, 'openalex')
    result = client.discover('https://doi.org/10.1234%2Frecent.2026?utm_source=link')
    assert result['doi'] == DOI
    assert session.get.call_count == 1


def test_discovery_does_not_extract_doi_from_unstructured_query():
    client, session = service({}, 'openalex')
    assert client.discover('find a recent paper like ' + DOI)['status'] == 'invalid'
    session.get.assert_not_called()


def test_prior_cli_persistent_cooldown_prevents_recent_api_request(tmp_path):
    from src.core.discovery_cache import DiscoveryCache
    first_cache = DiscoveryCache(directory=tmp_path, enabled=True)
    first_cache.set_cooldown('openalex_semantic', 3600)
    second_cache = DiscoveryCache(directory=tmp_path, enabled=True)
    client, session = service({}, 'openalex', cache=second_cache)
    result = client.discover(DOI)
    session.get.assert_not_called()
    assert result['errors']['openalex']['kind'] == 'rate_limited'
    assert result['errors']['openalex']['retry_after'] > 3500


def test_recent_429_persists_without_caching_metadata(tmp_path, monkeypatch):
    import sqlite3
    from src.core.discovery_cache import DiscoveryCache
    cache = DiscoveryCache(directory=tmp_path, enabled=True)
    client, session = service({}, 'openalex', cache=cache)
    session.get.return_value = response(status=429, headers={'Retry-After': '120'})
    client.discover(DOI)
    # Simulate a new process: throw away the in-memory cooldown singleton.
    monkeypatch.setattr(provider_limits, 'provider_cooldowns', provider_limits.ProviderCooldowns())
    second_cache = DiscoveryCache(directory=tmp_path, enabled=True)
    second, second_session = service({}, 'openalex', cache=second_cache)
    assert second.discover(DOI)['errors']['openalex']['kind'] == 'rate_limited'
    second_session.get.assert_not_called()
    with sqlite3.connect(cache.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM responses').fetchone()[0] == 0


def test_europepmc_confirmed_open_pmc_record_adds_official_cloud_pdf(monkeypatch):
    from src.acquisition import pmc_cloud
    cloud = Mock(return_value={'locations': [{'pdf_url': 'https://pmc-oa-opendata.s3.amazonaws.com/PMC123.2/PMC123.2.pdf',
        'version': 'acceptedVersion', 'license': 'CC BY', 'pmcid': 'PMC123',
        'metadata_url': 'https://pmc-oa-opendata.s3.amazonaws.com/metadata/PMC123.2.json', 'pmc_version': 2}], 'errors': {}})
    monkeypatch.setattr(pmc_cloud, 'discover_pmc_cloud', cloud)
    client, session = service({'resultList': {'result': [
        {'doi': '10.1234/wrong', 'pmcid': 'PMC999', 'isOpenAccess': 'Y'},
        {'doi': DOI, 'pmcid': 'PMC123', 'isOpenAccess': 'Y'},
    ]}}, 'europepmc')
    result = client.discover(DOI)
    assert result['locations'][0]['source'] == 'pmc_cloud'
    assert result['locations'][0]['version'] == 'acceptedVersion'
    assert result['locations'][0]['license'] == 'CC BY'
    assert result['locations'][0]['provenance'][0]['metadata_url'].endswith('PMC123.2.json')
    assert cloud.call_count == 1
    assert cloud.call_args.args[:2] == ('PMC123', DOI)
    assert cloud.call_args.kwargs['deadline'] <= client.deadline


def test_med_indexed_preprint_stays_alternative_by_publication_type():
    client, _ = service({'resultList': {'result': [{'doi': DOI, 'source': 'MED',
        'pubTypeList': {'pubType': ['Journal Article', 'Preprint']},
        'fullTextUrlList': {'fullTextUrl': [{'url': 'https://repo.edu/preprint.pdf',
            'documentStyle': 'pdf', 'availabilityCode': 'OA'}]}}]}}, 'europepmc')
    result = client.discover(DOI)
    assert not result['locations']
    assert result['alternatives'][0]['version'] == 'submittedVersion'
    assert result['alternatives'][0]['requires_selection'] is True


def test_cloud_does_not_promote_med_indexed_preprint_to_published_version(monkeypatch):
    from src.acquisition import pmc_cloud
    monkeypatch.setattr(pmc_cloud, 'discover_pmc_cloud', Mock(return_value={'locations': [{
        'pdf_url': 'https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/PMC123.1.pdf',
        'version': 'publishedVersion', 'license': 'CC BY', 'pmcid': 'PMC123',
        'metadata_url': 'https://pmc-oa-opendata.s3.amazonaws.com/metadata/PMC123.1.json'}], 'errors': {}}))
    client, _ = service({'resultList': {'result': [{'doi': DOI, 'source': 'MED',
        'pmcid': 'PMC123', 'isOpenAccess': 'Y',
        'pubTypeList': {'pubType': ['Preprint']}}]}}, 'europepmc')
    result = client.discover(DOI)
    assert not result['locations']
    assert result['alternatives'][0]['version'] == 'submittedVersion'
    assert result['alternatives'][0]['requires_selection'] is True
