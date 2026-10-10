"""Repository copies retain their identity, version and match evidence."""
from copy import deepcopy
from unittest.mock import Mock
import pytest
import requests
from src.acquisition.repository_discovery import RepositoryDiscovery
from src.core import provider_limits

DOI = '10.1234/article.2026'
TITLE = 'Engineering enzyme interfaces for efficient selective biocatalysis'
RECORD = {'doi': DOI, 'title': TITLE, 'authors': ['Maria García', 'Michael Smith'], 'year': 2026}


def client(data, provider='hal', status=200, **kwargs):
    response = Mock(status_code=status, headers={})
    response.json.return_value = data
    session = Mock()
    session.get.return_value = response
    cache = Mock()
    cache.cooldown_remaining.return_value = 0
    return RepositoryDiscovery(session=session, providers=[provider], cache=cache, **kwargs), session


def hal(**updates):
    result = {'doiId_s': DOI, 'title_s': [TITLE], 'authFullName_s': RECORD['authors'],
              'halId_s': 'hal-01234567', 'uri_s': 'https://hal.science/hal-01234567v1',
              'fileMain_s': 'https://hal.science/hal-01234567/document', 'docType_s': 'ART',
              'licence_s': 'https://creativecommons.org/licenses/by/4.0/', 'publicationDateY_i': 2026}
    result.update(updates)
    return {'response': {'docs': [result]}}


def zenodo(**updates):
    meta = {'doi': '10.5281/zenodo.12345', 'title': TITLE, 'creators': [{'name': 'García, Maria'}],
            'resource_type': {'type': 'publication', 'subtype': 'article'}, 'access_right': 'open',
            'related_identifiers': [{'identifier': DOI, 'relation': 'isIdenticalTo'}],
            'license': {'id': 'cc-by-4.0'}, 'publication_date': '2026-09-01'}
    meta.update(updates)
    return {'hits': {'hits': [{'id': 12345, 'doi': meta['doi'], 'metadata': meta,
                              'links': {'html': 'https://zenodo.org/records/12345'},
                              'files': [{'key': 'article.pdf', 'links': {'self': 'https://zenodo.org/api/records/12345/files/article.pdf/content'}}]}]}}


def test_hal_explicit_file_fields_and_unknown_version_not_published_inference():
    service, session = client(hal())
    result = service.discover(RECORD)
    item = result['locations'][0]
    assert item['doi'] == DOI and item['version'] == 'unknown'
    assert item['pdf_url'].endswith('/document') and item['downloadable']
    assert item['identity_evidence'] == 'exact_doi'
    assert item['license'].startswith('https://creativecommons')
    assert 'fileMain_s' in session.get.call_args.kwargs['params']['fl']
    assert session.get.call_count == 1
    session.get.return_value.close.assert_called_once()


def test_hal_different_doi_is_alternative_with_own_identity():
    service, _ = client(hal(doiId_s='10.1234/preprint', docType_s='UNDEFINED'))
    result = service.discover(RECORD)
    assert not result['locations']
    alternative = result['alternatives'][0]
    assert alternative['doi'] == '10.1234/preprint'
    assert alternative['record']['doi'] == '10.1234/preprint'
    assert alternative['record']['identifier'] == {'type': 'doi', 'value': '10.1234/preprint'}
    assert alternative['requested_doi'] == DOI and alternative['requires_selection']
    assert alternative['version'] == 'submittedVersion'
    assert alternative['record']['record_type'] == 'preprint'


def test_hal_no_doi_title_and_author_match_remains_explicit_alternative():
    service, _ = client(hal(doiId_s=None))
    item = service.discover(RECORD)['alternatives'][0]
    assert item['record']['identifier']['type'] == 'url'
    assert item['record']['doi'] is None and item['requires_selection']


@pytest.mark.parametrize('updates', [
    {'doiId_s': None, 'authFullName_s': ['Unrelated Researcher']},
    {'doiId_s': None, 'title_s': ['Different paper about enzyme interfaces']},
    {'docType_s': 'DATA'},
    {'title_s': ['Supporting information for ' + TITLE]},
    {'fileMain_s': 'https://evil.test/article.pdf', 'uri_s': 'http://127.0.0.1/admin'},
])
def test_hal_rejects_weak_identity_and_nonpapers(updates):
    service, _ = client(hal(**updates))
    result = service.discover(RECORD)
    assert not result['locations'] and not result['alternatives']


def test_exact_doi_conflicting_title_not_accepted():
    service, _ = client(hal(title_s=['An entirely different paper about fungal ecology']))
    assert not service.discover(RECORD)['locations']


def test_zenodo_explicit_identical_relation_has_provenance_and_deposit_identity():
    service, _ = client(zenodo(), 'zenodo')
    item = service.discover(RECORD)['locations'][0]
    assert item['doi'] == DOI and item['identity_evidence'] == 'isIdenticalTo'
    assert item['repository_doi'] == '10.5281/zenodo.12345'
    assert item['version'] == 'unknown' and item['license'] == 'cc-by-4.0'
    assert item['provenance'][0]['provider'] == 'zenodo'


@pytest.mark.parametrize('relation', ['cites', 'isSupplementTo', 'isSupplementedBy', 'isPartOf'])
def test_zenodo_nonidentity_relation_cannot_be_rescued_by_title(relation):
    service, _ = client(zenodo(related_identifiers=[{'identifier': DOI, 'relation': relation}]), 'zenodo')
    result = service.discover(RECORD)
    assert not result['locations'] and not result['alternatives']


def test_zenodo_preprint_related_version_requires_selection_and_own_doi():
    service, _ = client(zenodo(resource_type={'type': 'publication', 'subtype': 'preprint'},
        related_identifiers=[{'identifier': DOI, 'relation': 'isPreviousVersionOf'}]), 'zenodo')
    result = service.discover(RECORD)
    item = result['alternatives'][0]
    assert not result['locations'] and item['requires_selection']
    assert item['doi'] == '10.5281/zenodo.12345'
    assert item['record']['doi'] == item['doi'] and item['version'] == 'submittedVersion'


@pytest.mark.parametrize('updates', [{'resource_type': {'type': 'dataset'}}, {'access_right': 'closed'}, {'access_right': 'embargoed'}])
def test_zenodo_not_open_papers_no_download(updates):
    service, _ = client(zenodo(**updates), 'zenodo')
    result = service.discover(RECORD)
    assert not result['locations'] and not result['alternatives']


def test_zenodo_supplement_files_excluded_and_modern_response_supported():
    data = zenodo()
    hit = data['hits']['hits'][0]
    hit['metadata']['resource_type'] = {'id': 'publication-article'}
    hit['metadata']['creators'] = [{'person_or_org': {'name': 'García, Maria'}}]
    hit['metadata'].pop('access_right')
    hit['access'] = {'files': 'public'}
    hit['files'] = {'enabled': True, 'entries': {'paper.pdf': {'key': 'paper.pdf', 'links': {'content': 'https://zenodo.org/api/records/12345/files/paper.pdf/content'}}, 'SupportingInformation.pdf': {'key': 'SupportingInformation.pdf', 'links': {'content': 'https://zenodo.org/api/records/12345/files/SupportingInformation.pdf/content'}}}}
    service, _ = client(data, 'zenodo')
    result = service.discover(RECORD)
    assert len(result['locations']) == 1
    assert '/paper.pdf/' in result['locations'][0]['pdf_url']


def test_query_escapes_literals_without_injecting_solr_operators():
    service, session = client(hal())
    service.discover(dict(RECORD, title='A "quoted" enzyme: (test)'))
    query = session.get.call_args.kwargs['params']['q']
    assert r'\"quoted\"' in query and r'\:' in query and r'\(' in query


def test_network_errors_and_deadline_reported_not_missing(monkeypatch):
    service, session = client({})
    session.get.side_effect = requests.Timeout()
    assert service.discover(RECORD)['errors']['hal']['kind'] == 'timeout'
    service, session = client({})
    instants = iter([0, 20])
    monkeypatch.setattr('src.acquisition.repository_discovery.time.monotonic', lambda: next(instants))
    assert service.discover(RECORD)['errors']['hal']['kind'] == 'deadline'
    session.get.assert_not_called()


def test_persistent_cooldown_does_not_make_request():
    service, session = client({})
    service.cache.cooldown_remaining.return_value = 20
    result = service.discover(RECORD)
    assert result['errors']['hal']['kind'] == 'rate_limited'
    session.get.assert_not_called()


def test_invalid_or_empty_record_no_requests():
    service, session = client({})
    assert service.discover({})['status'] == 'invalid'
    session.get.assert_not_called()


def test_zenodo_preprint_keeps_own_doi_even_when_depositor_calls_it_identical():
    service, _ = client(zenodo(resource_type={'type': 'publication', 'subtype': 'preprint'}), 'zenodo')
    item = service.discover(RECORD)['alternatives'][0]
    assert item['record']['doi'] == '10.5281/zenodo.12345'
    assert item['doi'] == item['record']['doi'] and item['requested_doi'] == DOI


def test_inconsistent_dataset_type_is_rejected_despite_article_subtype():
    service, _ = client(zenodo(resource_type={'type': 'dataset', 'subtype': 'article'}), 'zenodo')
    assert not service.discover(RECORD)['locations']


def test_rate_limit_recorded_for_later_calls(monkeypatch):
    cooldowns = provider_limits.ProviderCooldowns()
    monkeypatch.setattr(provider_limits, 'provider_cooldowns', cooldowns)
    service, session = client({}, status=429)
    session.get.return_value.headers = {'Retry-After': '40'}
    result = service.discover(RECORD)
    assert result['errors']['hal']['kind'] == 'rate_limited'
    assert service.cache.set_cooldown.call_args.args[0] == 'hal'
    service.discover(RECORD)
    assert session.get.call_count == 1
