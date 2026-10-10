"""Current PMC cloud metadata replaces the retired oa.fcgi service."""
import json
from unittest.mock import Mock

import pytest

from src.acquisition.pmc_cloud import discover_pmc_cloud
from src.core.discovery_cache import DiscoveryCache

PMC = 'PMC13572967'
DOI = '10.1002/cbic.70489'
BASE = 'https://pmc-oa-opendata.s3.amazonaws.com/'


def response(data, status=200, headers=None):
    raw = data if isinstance(data, str) else json.dumps(data)
    return Mock(status_code=status, headers=headers or {}, iter_content=Mock(return_value=[raw.encode()]))


def listing(*versions):
    return '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>' + ''.join('<Contents><Key>metadata/'+PMC+'.'+str(v)+'.json</Key></Contents>' for v in versions) + '</ListBucketResult>'


def metadata(version=1, **extra):
    return {'pmcid':PMC, 'doi':DOI, 'version':version, 'is_pmc_openaccess':True,
            'is_manuscript':False, 'is_retracted':False, 'license_code':'CC BY',
            'pdf_url':f's3://pmc-oa-opendata/{PMC}.{version}/{PMC}.{version}.pdf?md5=abc', **extra}


def test_lists_actual_versions_and_converts_only_official_s3_pdf_urls():
    session = Mock()
    session.get.side_effect = [response(listing(2, 3)), response(metadata(2, is_manuscript=True)), response(metadata(3))]
    result = discover_pmc_cloud(PMC, DOI, session=session)
    assert not result['errors']
    assert [x['version'] for x in result['locations']] == ['acceptedVersion', 'publishedVersion']
    assert result['locations'][0]['pdf_url'] == BASE+PMC+'.2/'+PMC+'.2.pdf?md5=abc'
    assert result['locations'][0]['license'] == 'CC BY'
    assert session.get.call_args_list[0].kwargs['params']['prefix'] == 'metadata/'+PMC+'.'
    assert session.get.call_count == 3
    for call in session.get.call_args_list:
        assert call.kwargs['stream'] is True


@pytest.mark.parametrize('change', [
    {'doi':'10.1234/wrong'}, {'pmcid':'PMC999'}, {'is_pmc_openaccess':False},
    {'pdf_url':None}, {'pdf_url':'s3://other-bucket/a.pdf'},
    {'pdf_url':'https://evil.example/file.pdf'}, {'pdf_url':'s3://pmc-oa-opendata/PMC999.1/file.pdf'},
    {'is_retracted':True},
])
def test_unconfirmed_wrong_unavailable_or_retracted_copy_is_not_downloadable(change):
    session = Mock()
    session.get.side_effect = [response(listing(1)), response(metadata(**change))]
    assert not discover_pmc_cloud(PMC, DOI, session=session)['locations']


def test_request_sizes_are_bounded_and_closed():
    session = Mock()
    result = response('x'*1000)
    session.get.return_value = result
    output = discover_pmc_cloud(PMC, DOI, session=session, max_bytes=100)
    assert not output['locations']
    assert output['errors']
    result.close.assert_called_once()


def test_429_persists_cooldown_without_retries(tmp_path):
    cache = DiscoveryCache(tmp_path, enabled=True)
    session = Mock()
    session.get.return_value = response('', status=429, headers={'Retry-After':'300'})
    result = discover_pmc_cloud(PMC, DOI, session=session, cache=cache)
    assert result['errors']['pmc_cloud']['kind'] == 'rate_limited'
    discover_pmc_cloud(PMC, DOI, session=session, cache=cache)
    assert session.get.call_count == 1


def test_wrong_listing_prefix_never_requested():
    session = Mock()
    session.get.return_value = response('<ListBucketResult><Contents><Key>metadata/PMC999.1.json</Key></Contents></ListBucketResult>')
    assert not discover_pmc_cloud(PMC, DOI, session=session)['locations']
    assert session.get.call_count == 1


def test_invalid_pmcid_makes_no_network_request():
    session = Mock()
    assert not discover_pmc_cloud('../secret', DOI, session=session)['locations']
    session.get.assert_not_called()
