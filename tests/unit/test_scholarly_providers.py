"""Independent literature indexes preserve identity and bounded request behavior."""
import requests

from src.core.discovery import DiscoveryService

TITLE = 'Highly accurate protein structure prediction with AlphaFold'
DOI = '10.1038/s41586-021-03819-2'


class Response:
    status_code = 200
    headers = {}
    def __init__(self, payload=None, text=''):
        self.payload, self.text = payload, text
    def json(self):
        return self.payload


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def epmc(**updates):
    row = {'id': '34265844', 'source': 'MED', 'pmid': '34265844', 'pmcid': 'PMC8371605',
           'doi': DOI, 'title': TITLE, 'pubYear': '2021',
           'authorList': {'author': [{'fullName': 'Jumper J', 'firstName': 'John', 'lastName': 'Jumper'}]},
           'journalInfo': {'journal': {'title': 'Nature'}},
           'abstractText': '<p>Protein structure prediction.</p>',
           'fullTextUrlList': {'fullTextUrl': [
               {'documentStyle': 'pdf', 'availability': 'Open access', 'url': 'https://example.org/alphafold.pdf'},
               {'documentStyle': 'html', 'url': 'https://example.org/alphafold'},
               {'documentStyle': 'pdf', 'url': 'javascript:bad'}]}}
    row.update(updates)
    return row


def test_europepmc_metadata_can_identify_without_other_indexes():
    session = Session(Response({'resultList': {'result': [epmc()]}}))
    result = DiscoveryService(session=session, providers=('europepmc',)).search(TITLE)
    record = result['selected']
    assert result['status'] == 'matched'
    assert record['doi'] == DOI
    assert record['pmid'] == '34265844' and record['pmcid'] == 'PMC8371605'
    assert record['authors'] == ['John Jumper']
    assert record['year'] == 2021 and record['journal'] == 'Nature'
    assert record['abstract'] == 'Protein structure prediction.'
    assert record['pdf_urls'] == ['https://example.org/alphafold.pdf']
    assert session.calls[0][1]['params']['resultType'] == 'core'
    assert session.calls[0][1]['timeout'] <= 8


def test_europepmc_without_doi_keeps_pubmed_identifier():
    session = Session(Response({'resultList': {'result': [epmc(doi=None)]}}))
    record = DiscoveryService(session=session, providers=('europepmc',)).search(TITLE)['selected']
    assert record['identifier'] == {'type': 'pmid', 'value': '34265844'}
    assert record['url'] == 'https://europepmc.org/article/MED/34265844'


def test_europepmc_doi_lookup_filters_wrong_and_retracted_records():
    session = Session(Response({'resultList': {'result': [epmc(doi='10.1234/wrong'), epmc(isRetracted='Y')]}}))
    result = DiscoveryService(session=session, providers=('europepmc',)).search(DOI)
    assert result['status'] == 'ambiguous'
    assert len(result['candidates']) == 1
    assert 'Retracted' in str(result['candidates'][0]['match_reasons'])
    assert session.calls[0][1]['params']['query'] == 'DOI:"' + DOI + '"'


def test_europepmc_invalid_schema_is_not_empty_success():
    result = DiscoveryService(session=Session(Response({'resultList': []})), providers=('europepmc',)).search(TITLE)
    assert result['status'] == 'unavailable'
    assert result['errors']['europepmc']['kind'] == 'invalid_response'


ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title>
<published>2017-06-12T17:57:34Z</published><author><name>Ashish Vaswani</name></author>
<summary>The dominant sequence transduction models.</summary><arxiv:doi>10.5555/published</arxiv:doi>
<link href="http://arxiv.org/pdf/1706.03762v7" title="pdf" type="application/pdf"/>
</entry></feed>'''


def test_arxiv_preserves_preprint_identity_and_published_doi_separately():
    session = Session(Response(text=ATOM))
    result = DiscoveryService(session=session, providers=('arxiv',)).search('Vaswani 2017 Attention Is All You Need')
    record = result['selected']
    assert record['identifier'] == {'type': 'arxiv', 'value': '1706.03762v7'}
    assert record['doi'] is None
    assert record['related_doi'] == '10.5555/published'
    assert record['year'] == 2017 and record['authors'] == ['Ashish Vaswani']
    assert record['pdf_urls'] == ['https://arxiv.org/pdf/1706.03762v7']
    assert session.calls[0][1]['params']['search_query'] == 'ti:"Attention Is All You Need"'


def test_arxiv_spacing_is_shared_between_searches_without_sleep():
    session = Session(Response(text=ATOM))
    DiscoveryService(session=session, providers=('arxiv',)).search('Attention Is All You Need')
    second = DiscoveryService(session=session, providers=('arxiv',)).search('Attention Is All You Need')
    assert second['status'] == 'unavailable'
    assert second['errors']['arxiv']['kind'] == 'rate_limited'
    assert len(session.calls) == 1


def test_arxiv_error_atom_is_visible_not_no_results():
    text = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_123</id><title>Error</title></entry></feed>'
    result = DiscoveryService(session=Session(Response(text=text)), providers=('arxiv',)).search('bad query')
    assert result['status'] == 'unavailable'
    assert result['errors']['arxiv']['kind'] == 'invalid_response'


def test_arxiv_never_uses_published_doi_as_preprint_identity():
    session = Session(Response(text=ATOM))
    result = DiscoveryService(session=session, providers=('arxiv',)).search('10.5555/published')
    assert result['status'] == 'not_found'
    assert session.calls == []


def test_default_provider_list_has_independent_biomedical_and_repository_sources():
    assert 'europepmc' in DiscoveryService.PROVIDERS
    assert 'arxiv' in DiscoveryService.PROVIDERS


def test_repository_fields_survive_same_doi_metadata_merge():
    from src.core.discovery import _crossref, _deduplicate, _europepmc
    records = _deduplicate([_crossref({'DOI': DOI, 'title': [TITLE]}),
                            _europepmc(epmc(firstPublicationDate='2021-07-15'))])
    assert len(records) == 1
    assert records[0]['pmcid'] == 'PMC8371605'
    assert records[0]['pmid'] == '34265844'
    assert records[0]['publication_date'] == '2021-07-15'
    assert records[0]['pdf_urls'] == ['https://example.org/alphafold.pdf']


def test_europepmc_missing_identifiers_does_not_merge_unrelated_titles():
    from src.core.discovery import _deduplicate, _europepmc
    records = [_europepmc({'title': 'Novel substrate screening in 2025'}),
               _europepmc({'title': 'Discovery of a new enzymatic reaction'})]
    assert len(_deduplicate(records)) == 2


def test_arxiv_entity_response_is_rejected():
    response = Response(text='<!DOCTYPE feed [<!ENTITY x "expanded">]><feed xmlns="http://www.w3.org/2005/Atom"/>')
    result = DiscoveryService(session=Session(response), providers=('arxiv',)).search(TITLE)
    assert result['errors']['arxiv']['kind'] == 'invalid_response'


def test_arxiv_not_called_for_already_matched_default_search(monkeypatch):
    service = DiscoveryService()
    calls = []
    def fetch(provider, query, count, exact_doi, remaining, now=None):
        from src.core.discovery import _europepmc
        calls.append(provider)
        return ([_europepmc(epmc())], None) if provider == 'europepmc' else ([], None)
    monkeypatch.setattr(service, '_fetch', fetch)
    assert service.search(TITLE)['status'] == 'matched'
    assert 'arxiv' not in calls


def test_europepmc_still_works_if_other_indexes_unavailable(monkeypatch):
    service = DiscoveryService()
    def fetch(provider, query, count, exact_doi, remaining, now=None):
        from src.core.discovery import _europepmc
        return ([_europepmc(epmc())], None) if provider == 'europepmc' else ([], {'kind': 'rate_limited'})
    monkeypatch.setattr(service, '_fetch', fetch)
    result = service.search(TITLE)
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['doi'] == DOI
    assert result['selected'] is None


def test_europepmc_preprint_is_labeled_and_keeps_its_own_doi():
    from src.core.discovery import _europepmc
    record = _europepmc(epmc(source='PPR', id='PPR123', pmid='', pmcid='', doi='10.1101/2026.09.01.123456'))
    assert record['record_type'] == 'preprint'
    assert record['doi'] == '10.1101/2026.09.01.123456'
