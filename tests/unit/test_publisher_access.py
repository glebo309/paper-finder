"""Publisher access evidence is separate from index availability or HTTP blocks."""
import json

from src.acquisition.publisher_access import discover_publisher_access

DOI = '10.1234/recent'
URL = 'https://publisher.example/article/recent'


class Response:
    def __init__(self, text='', status=200, headers=None, url=URL):
        self.body = text.encode()
        self.status_code = status
        self.headers = {'Content-Type': 'text/html', **(headers or {})}
        self.url = url
        self.closed = False
    def iter_content(self, chunk_size):
        yield self.body
    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def page(doi=DOI, free=True, license=None):
    scholarly = {'@type': 'ScholarlyArticle', 'identifier': doi, 'isAccessibleForFree': free}
    if license:
        scholarly['license'] = license
    return '<meta name="citation_doi" content="' + doi + '"><meta name="citation_pdf_url" content="/paper.pdf"><script type="application/ld+json">' + json.dumps(scholarly) + '</script>'


def test_normal_doi_redirect_and_explicit_open_publisher_metadata():
    redirect = Response(status=302, headers={'Location': URL})
    response = Response(page())
    session = Session(redirect, response)
    result = discover_publisher_access(DOI, session=session)
    assert result['status'] == 'found'
    location = result['locations'][0]
    assert location['pdf_url'] == 'https://publisher.example/paper.pdf'
    assert location['version'] == 'unknown'  # Publisher origin does not prove manuscript version.
    assert location['availability'] == 'open'
    assert session.calls[0][0] == 'https://doi.org/10.1234/recent'
    assert all(call[1]['allow_redirects'] is False for call in session.calls)
    assert redirect.closed and response.closed


def test_http_block_is_not_labeled_closed_and_not_retried():
    session = Session(Response(status=403))
    result = discover_publisher_access(DOI, session=session)
    assert result['status'] == 'blocked'
    assert result['locations'] == []
    assert len(session.calls) == 1


def test_free_website_or_navigation_does_not_prove_free_article():
    html = '<meta name="citation_doi" content="' + DOI + '"><meta name="citation_pdf_url" content="/paper.pdf"><script type="application/ld+json">{"@type":"WebSite","isAccessibleForFree":true}</script>'
    result = discover_publisher_access(DOI, session=Session(Response(html)))
    assert result['status'] == 'unknown'
    assert result['locations'] == []


def test_explicit_false_with_pdf_link_is_closed_not_downloadable():
    result = discover_publisher_access(DOI, session=Session(Response(page(free=False))))
    assert result['status'] == 'closed'
    assert result['locations'] == []


def test_conflicting_doi_cannot_establish_publisher_access():
    result = discover_publisher_access(DOI, session=Session(Response(page(doi='10.1234/other'))))
    assert result['status'] == 'identity_mismatch'
    assert result['locations'] == []


def test_open_license_preserved_with_verified_publisher_evidence():
    license = 'https://creativecommons.org/licenses/by/4.0/'
    result = discover_publisher_access(DOI, session=Session(Response(page(license=license))))
    assert result['locations'][0]['license'] == license


def test_redirect_budget_enforced():
    session = Session(*(Response(status=302, headers={'Location': URL}) for _ in range(4)))
    result = discover_publisher_access(DOI, session=session, max_requests=3)
    assert result['status'] == 'unavailable'
    assert len(session.calls) == 3


def test_page_byte_budget_enforced():
    result = discover_publisher_access(DOI, session=Session(Response(page())), max_bytes=10)
    assert result['status'] == 'unavailable'
    assert result['locations'] == []


def _recent_client(monkeypatch, publisher_result, *, index_locations=None, deadline=20):
    from unittest.mock import Mock
    from src.acquisition.recent_open_access import RecentOpenAccessDiscovery
    response = Mock(status_code=200, headers={})
    response.json.return_value = {'doi': DOI, 'locations': index_locations or []}
    session = Mock()
    session.get.return_value = response
    calls = []
    def publisher(doi, **kwargs):
        calls.append((doi, kwargs))
        return publisher_result
    monkeypatch.setattr('src.acquisition.publisher_access.discover_publisher_access', publisher)
    client = RecentOpenAccessDiscovery(session=session, providers=['openalex'], deadline=deadline)
    return client, calls


def test_recent_fallback_publisher_open_overrides_stale_index_closed(monkeypatch):
    from src.acquisition.recent_open_access import _location
    publisher = {'doi': DOI, 'status': 'found', 'locations': [
        _location('publisher', DOI, pdf='https://publisher.example/paper.pdf', landing=URL,
                  version='unknown', license='https://creativecommons.org/licenses/by/4.0/')], 'errors': {}}
    client, calls = _recent_client(monkeypatch, publisher, index_locations=[
        {'is_oa': False, 'landing_page_url': URL, 'version': 'publishedVersion'}])
    result = client.discover(DOI)
    assert result['status'] == 'found'
    assert result['locations'][0]['source'] == 'publisher'
    assert result['closed'][0]['availability'] == 'closed'
    assert result['publisher_access']['status'] == 'found'
    assert calls[0][0] == DOI
    assert 0 < calls[0][1]['timeout'] <= 8


def test_recent_fallback_skips_publisher_when_known_open_pdf_exists(monkeypatch):
    client, calls = _recent_client(monkeypatch, {}, index_locations=[
        {'is_oa': True, 'pdf_url': 'https://repo.example/article.pdf', 'version': 'acceptedVersion'}])
    assert client.discover(DOI)['status'] == 'found'
    assert calls == []


def test_recent_publisher_http_block_visible_with_human_message(monkeypatch):
    client, calls = _recent_client(monkeypatch, {'doi': DOI, 'status': 'blocked', 'locations': [],
                                              'errors': {'publisher': {'kind': 'http', 'status': 403}}})
    result = client.discover(DOI)
    assert result['publisher_access']['status'] == 'blocked'
    assert result['errors']['publisher']['status'] == 403
    assert 'blocked' in result['errors']['publisher']['message'].lower()
    assert result['status'] != 'closed'


def test_recent_publisher_fallback_respects_shared_request_deadline(monkeypatch):
    client, calls = _recent_client(monkeypatch, {}, deadline=1)
    moments = iter([0, 0, 2, 2, 2])
    monkeypatch.setattr('src.acquisition.recent_open_access.time.monotonic', lambda: next(moments, 2))
    result = client.discover(DOI)
    assert calls == []
    assert result['errors']['publisher']['kind'] == 'deadline'
