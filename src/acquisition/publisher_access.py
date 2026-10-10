"""Bounded publisher-declared article access, independent of index freshness.

Only normal DOI redirects and advertised main-article PDF URLs are followed.
HTTP denial is reported as blocked, never as evidence that an article is closed.
Schema.org article access flags describe reading access; licenses remain distinct.
"""
from html.parser import HTMLParser
import json
import time
from urllib.parse import quote, urljoin

import requests

from .recent_open_access import _doi, _url, _location


class _PublisherMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dois, self.pdfs, self.scripts = [], [], []
        self.active_script = None
    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value or '' for key, value in attrs}
        name = (attrs.get('name') or attrs.get('property') or '').lower()
        if tag == 'meta' and name == 'citation_doi':
            self.dois.append(_doi(attrs.get('content')))
        if tag == 'meta' and name == 'citation_pdf_url':
            self.pdfs.append(attrs.get('content'))
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.active_script = []
    def handle_data(self, data):
        if self.active_script is not None:
            self.active_script.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.active_script is not None:
            try:
                self.scripts.append(json.loads(''.join(self.active_script)))
            except (ValueError, TypeError):
                pass
            self.active_script = None


def _articles(value):
    """Inspect article objects and @graph without inheriting website flags."""
    if isinstance(value, list):
        for child in value:
            yield from _articles(child)
    elif isinstance(value, dict):
        kinds = value.get('@type', [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if isinstance(kinds, list) and any(kind in ('ScholarlyArticle', 'Article', 'MedicalScholarlyArticle') for kind in kinds):
            yield value
        yield from _articles(value.get('@graph', []))


def _article_dois(article):
    values = article.get('identifier', [])
    values = values if isinstance(values, list) else [values]
    values += [article.get('sameAs'), article.get('url'), article.get('@id')]
    result = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get('value')
        doi = _doi(value) if isinstance(value, str) else None
        if doi:
            result.add(doi)
    return result


def discover_publisher_access(doi, session=None, timeout=8, max_bytes=1024 * 1024, max_requests=3):
    """Return publisher access evidence, or an explicit unknown/blocked outcome."""
    expected = _doi(doi)
    result = {'doi': expected, 'status': 'invalid', 'locations': [], 'errors': {}}
    if not expected:
        return result
    result['status'] = 'unknown'
    owned_session = session is None
    session = session or requests.Session()
    current = 'https://doi.org/' + quote(expected, safe='/')
    deadline = time.monotonic() + max(.1, float(timeout))
    try:
        for hop in range(max(1, min(int(max_requests), 5))):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.update(status='unavailable', errors={'publisher': {'kind': 'deadline'}})
                return result
            response = None
            try:
                response = session.get(current, stream=True, allow_redirects=False, timeout=remaining,
                                       headers={'User-Agent': 'PaperFinder/2 (publisher access metadata)'})
                result['landing_page_url'] = current
                headers = {key.lower(): value for key, value in response.headers.items()}
                if response.status_code in (301, 302, 303, 307, 308):
                    current = _url(urljoin(current, headers.get('location', '')))
                    if current:
                        continue
                    result.update(status='unavailable', errors={'publisher': {'kind': 'invalid_redirect'}})
                    return result
                if response.status_code in (401, 403, 429):
                    result.update(status='blocked', errors={'publisher': {'kind': 'http', 'status': response.status_code}})
                    return result
                if response.status_code != 200:
                    result.update(status='unavailable', errors={'publisher': {'kind': 'http', 'status': response.status_code}})
                    return result
                content_type = headers.get('content-type', '').lower().split(';')[0]
                if content_type not in ('text/html', 'application/xhtml+xml'):
                    return result
                if headers.get('content-length') and int(headers['content-length']) > max_bytes:
                    result.update(status='unavailable', errors={'publisher': {'kind': 'size_limit'}})
                    return result
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    if time.monotonic() >= deadline or len(body) + len(chunk) > max_bytes:
                        result.update(status='unavailable', errors={'publisher': {'kind': 'read_budget'}})
                        return result
                    body.extend(chunk)
                metadata = _PublisherMetadata()
                metadata.feed(body.decode('utf-8', errors='replace'))
                if metadata.dois and any(value != expected for value in metadata.dois):
                    result['status'] = 'identity_mismatch'
                    return result
                articles = list(_articles(metadata.scripts))
                matching = [article for article in articles if _article_dois(article) == {expected}
                            or (not _article_dois(article) and metadata.dois == [expected] and len(articles) == 1)]
                if not matching:
                    return result
                flags = [article.get('isAccessibleForFree') for article in matching]
                if False in flags or 'false' in flags:
                    result['status'] = 'closed' if not any(flag is True or flag == 'true' for flag in flags) else 'unknown'
                    return result
                if not any(flag is True or flag == 'true' for flag in flags):
                    return result
                license_url = next((_url(article.get('license')) for article in matching if _url(article.get('license'))), None)
                landing = _url(response.url) or current
                pdfs = list(dict.fromkeys(_url(urljoin(landing, value)) for value in metadata.pdfs if value))
                for pdf in [pdf for pdf in pdfs if pdf]:
                    location = _location('publisher', expected, pdf=pdf, landing=landing,
                                         version='unknown', license=license_url, host_type='publisher')
                    location['provenance'][0]['evidence'] = 'DOI-confirmed article isAccessibleForFree'
                    result['locations'].append(location)
                if not result['locations']:
                    result['locations'].append(_location('publisher', expected, landing=landing,
                                                         version='unknown', license=license_url, host_type='publisher'))
                result['status'] = 'found'
                return result
            except requests.RequestException:
                result.update(status='unavailable', errors={'publisher': {'kind': 'network'}})
                return result
            except (ValueError, TypeError):
                result.update(status='unavailable', errors={'publisher': {'kind': 'invalid_response'}})
                return result
            finally:
                if response is not None:
                    response.close()
        result.update(status='unavailable', errors={'publisher': {'kind': 'redirect_budget'}})
        return result
    finally:
        if owned_session:
            session.close()
