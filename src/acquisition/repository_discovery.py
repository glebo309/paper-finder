"""Bounded HAL/Zenodo metadata discovery with explicit alternate identities.

Sources: https://api.archives-ouvertes.fr/docs/search and
https://developers.zenodo.org/ (related identifiers, files and access rights).
The repository's article classification does not establish the file's version.
A repository DOI different from the requested DOI remains a selectable separate
record unless the deposit explicitly declares an identical/alternate identifier.
No files are downloaded and no publisher/index API is queried here.
"""
from difflib import SequenceMatcher
import html
import math
import re
import time
import unicodedata
from urllib.parse import urlsplit

import requests

from src.acquisition.recent_open_access import _doi, _location, _url
from src.core import provider_limits
from src.core.discovery_cache import DiscoveryCache


def _text(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(re.sub(r'<[^>]+>', ' ', value))
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', value))


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _items(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _literal(value):
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r'\\\1', value)


def _supplement(value):
    compact = re.sub(r'\W+', '', str(value)).casefold()
    return any(word in compact for word in ('supportinginformation', 'supplementary', 'supplemental', 'supplement', 'appendix'))


def _provider_url(value, provider):
    value = _url(value)
    if not value:
        return None
    host = urlsplit(value).hostname.lower()
    domains = ('hal.science', 'archives-ouvertes.fr') if provider == 'hal' else ('zenodo.org',)
    return value if any(host == domain or host.endswith('.' + domain) for domain in domains) else None


def _title_score(expected, actual):
    a, b = _text(expected), _text(actual)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _strong_match(record, title, authors):
    # Two independent metadata signals are required for title-based discovery.
    if len(_text(record.get('title')).split()) < 4 or _title_score(record.get('title'), title) < .92:
        return False
    expected_authors = record.get('authors') or []
    for expected in expected_authors:
        if isinstance(expected, dict):
            expected = expected.get('name') or expected.get('display_name') or ' '.join([expected.get('given', ''), expected.get('family', '')])
        parts = set(_text(expected).split())
        if len(parts) < 2:
            continue
        for actual in authors:
            # Full names in either surname-first or given-name-first order.
            actual_parts = set(_text(actual).split())
            if parts <= actual_parts or actual_parts <= parts and len(actual_parts) >= 2:
                return True
    return False


def _canonical(doi, title, authors, landing, year, preprint):
    record = {'doi': doi, 'title': title, 'authors': authors, 'year': year,
              'url': landing, 'record_urls': [landing] if landing else [],
              'record_type': 'preprint' if preprint else 'article'}
    record['identifier'] = {'type': 'doi', 'value': doi} if doi else {'type': 'url', 'value': landing}
    return record


class RepositoryDiscovery:
    """At most one metadata search per provider within a shared deadline.

    The report uses locations/alternatives/errors/status. Every alternative has
    its own canonical `record`, requested_doi and requires_selection=True; it
    must not be silently downloaded as the requested publication. Published or
    accepted versions are only labelled when explicitly supplied by metadata.
    A missing result is not evidence that no repository copy exists.
    """
    PROVIDERS = ('hal', 'zenodo')
    HAL_FIELDS = 'halId_s,title_s,authFullName_s,doiId_s,docType_s,fileMain_s,uri_s,licence_s,publicationDateY_i'

    def __init__(self, session=None, timeout=5, deadline=15, providers=None, cache=None):
        self.session = session or requests.Session()
        self.timeout = max(.1, float(timeout))
        self.deadline = max(.1, float(deadline))
        self.providers = tuple(providers) if providers is not None else self.PROVIDERS
        if any(provider not in self.PROVIDERS for provider in self.providers):
            raise ValueError('Unknown repository discovery provider')
        self.cache = cache if cache is not None else DiscoveryCache()

    def _request(self, provider, record, doi, remaining):
        delay = max(provider_limits.remaining(provider), self.cache.cooldown_remaining(provider))
        if delay:
            return None, {'kind': 'rate_limited', 'message': 'Repository is cooling down.', 'retry_after': math.ceil(delay)}
        title = record.get('title') or ''
        terms = []
        if provider == 'hal':
            if doi:
                terms.append('doiId_s:"' + _literal(doi) + '"')
            if title:
                terms.append('title_t:"' + _literal(title) + '"')
            url = 'https://api.archives-ouvertes.fr/search/'
            params = {'q': ' OR '.join(terms), 'wt': 'json', 'rows': 10,
                      'fl': self.HAL_FIELDS, 'fq': 'submitType_s:file'}
        else:
            # Search literal terms, then inspect structured relations locally.
            # This works across Zenodo's legacy/current search field schemas.
            terms = ['"' + _literal(value) + '"' for value in (doi, title) if value]
            url = 'https://zenodo.org/api/records'
            params = {'q': ' OR '.join(terms), 'size': 10, 'sort': 'bestmatch'}
        response = None
        try:
            response = self.session.get(url, params=params, timeout=min(self.timeout, remaining),
                headers={'Accept': 'application/json', 'User-Agent': 'PaperFinder/2 (repository metadata discovery)'})
            if response.status_code == 429:
                delay = provider_limits.record_limit(provider, response.headers.get('Retry-After'))
                self.cache.set_cooldown(provider, delay)
                return None, {'kind': 'rate_limited', 'message': 'Repository rate limit reached.', 'retry_after': math.ceil(delay)}
            if response.status_code != 200:
                return None, {'kind': 'http', 'message': f'Repository returned HTTP {response.status_code}.'}
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Unexpected response')
            return data, None
        except requests.Timeout:
            return None, {'kind': 'timeout', 'message': 'Repository metadata search timed out.'}
        except requests.RequestException:
            return None, {'kind': 'network', 'message': 'Repository metadata search failed.'}
        except (ValueError, TypeError):
            return None, {'kind': 'schema', 'message': 'Repository returned invalid metadata.'}
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _make(provider, requested, own_doi, title, authors, landing, pdf, version,
              license, year, evidence, identical=False):
        location_doi = requested if identical and version != 'submittedVersion' else own_doi
        item = _location(provider, location_doi, pdf=pdf, landing=landing,
                         version=version, license=license, host_type='repository')
        if not item:
            return None
        item.update({'requested_doi': requested, 'repository_doi': own_doi,
                     'identity_evidence': evidence, 'record': _canonical(location_doi, title, authors, landing,
                                                                       year, version == 'submittedVersion')})
        item['requires_selection'] = bool(version == 'submittedVersion' or not identical)
        item['record']['pdf_urls'] = [pdf] if pdf else []
        item['record']['source'] = provider
        item['provenance'][0].update({'repository_doi': own_doi, 'identity_evidence': evidence})
        return item

    @classmethod
    def _hal(cls, record, doi, data):
        response = data.get('response')
        if not isinstance(response, dict) or not isinstance(response.get('docs'), list):
            raise ValueError('Missing HAL records')
        output = []
        for doc in _items(response['docs'])[:10]:
            if doc.get('docType_s') not in ('ART', 'UNDEFINED', 'COMM'):
                continue
            title = _first(doc.get('title_s')) or ''
            if not isinstance(title, str) or _supplement(title):
                continue
            own_doi = _doi(_first(doc.get('doiId_s')))
            authors = [name for name in doc.get('authFullName_s', []) if isinstance(name, str)]
            identical = bool(doi and own_doi == doi)
            if identical:
                if record.get('title') and _title_score(record['title'], title) < .6:
                    continue
                evidence = 'exact_doi'
            elif _strong_match(record, title, authors):
                evidence = 'title_and_author'
            else:
                continue
            landing = _provider_url(doc.get('uri_s'), 'hal')
            pdf = _provider_url(_first(doc.get('fileMain_s')), 'hal')
            if not landing and not pdf:
                continue
            version = 'submittedVersion' if doc['docType_s'] == 'UNDEFINED' else 'unknown'
            item = cls._make('hal', doi, own_doi, title, authors, landing, pdf, version,
                             _first(doc.get('licence_s')), doc.get('publicationDateY_i'), evidence, identical)
            if item:
                output.append(item)
        return output

    @classmethod
    def _zenodo(cls, record, doi, data):
        hits = data.get('hits')
        if not isinstance(hits, dict) or not isinstance(hits.get('hits'), list):
            raise ValueError('Missing Zenodo records')
        output = []
        for hit in _items(hits['hits'])[:10]:
            meta = hit.get('metadata')
            if not isinstance(meta, dict):
                continue
            resource = meta.get('resource_type') or {}
            if resource.get('type') and resource['type'] != 'publication':
                continue
            kind = resource.get('subtype') or resource.get('id', '').removeprefix('publication-')
            if kind not in ('article', 'preprint', 'conferencepaper'):
                continue
            access = meta.get('access_right') or (hit.get('access') or {}).get('files')
            if access not in ('open', 'public'):
                continue
            title = meta.get('title') or ''
            if not isinstance(title, str) or _supplement(title):
                continue
            own_doi = _doi(meta.get('doi') or hit.get('doi'))
            authors = []
            for author in _items(meta.get('creators')):
                person = author.get('person_or_org') or {}
                name = author.get('name') or person.get('name') or ' '.join(filter(None, [person.get('given_name'), person.get('family_name')]))
                if name:
                    authors.append(name)
            relations = [rel.get('relation') for rel in _items(meta.get('related_identifiers'))
                         if doi and _doi(rel.get('identifier')) == doi]
            if any(rel in ('isSupplementTo', 'isSupplementedBy', 'cites', 'isPartOf', 'hasPart', 'references') for rel in relations):
                continue
            identical = bool(doi and (own_doi == doi or any(rel in ('isIdenticalTo', 'isAlternateIdentifier') for rel in relations)))
            if identical:
                if record.get('title') and _title_score(record['title'], title) < .6:
                    continue
                evidence = 'exact_doi' if own_doi == doi else next(rel for rel in relations if rel in ('isIdenticalTo', 'isAlternateIdentifier'))
            elif _strong_match(record, title, authors):
                evidence = next((rel for rel in relations if rel in ('isPreviousVersionOf', 'isNewVersionOf', 'isVersionOf', 'isPreprintOf')), 'title_and_author')
            else:
                continue
            landing = _provider_url((hit.get('links') or {}).get('html') or (hit.get('links') or {}).get('self_html'), 'zenodo')
            files = hit.get('files') or []
            if isinstance(files, dict):
                files = list((files.get('entries') or {}).values())
            pdfs = []
            for file in _items(files):
                name = file.get('key') or file.get('filename') or ''
                if not name.lower().endswith('.pdf') or _supplement(name):
                    continue
                links = file.get('links') or {}
                pdf = _provider_url(links.get('content') or links.get('self'), 'zenodo')
                if pdf:
                    pdfs.append(pdf)
            version = 'submittedVersion' if kind == 'preprint' else meta.get('version')
            version = version if version in ('submittedVersion', 'acceptedVersion', 'publishedVersion') else 'unknown'
            license = meta.get('license') or {}
            license = license.get('id') if isinstance(license, dict) else license
            year = str(meta.get('publication_date') or '')[:4]
            year = int(year) if year.isdigit() else None
            for pdf in pdfs or [None]:
                item = cls._make('zenodo', doi, own_doi, title, authors, landing, pdf,
                                 version, license, year, evidence, identical)
                if item:
                    output.append(item)
        return output

    def discover(self, record):
        report = {'doi': None, 'locations': [], 'alternatives': [], 'errors': {}, 'status': 'invalid'}
        if not isinstance(record, dict):
            return report
        identifier = record.get('identifier') or {}
        doi = _doi(record.get('doi') or (identifier.get('value') if isinstance(identifier, dict) and identifier.get('type') == 'doi' else None))
        report['doi'] = doi
        if not doi and not (isinstance(record.get('title'), str) and record['title'].strip() and record.get('authors')):
            return report
        started = time.monotonic()
        seen = set()
        for provider in self.providers:
            remaining = self.deadline - (time.monotonic() - started)
            if remaining <= 0:
                report['errors'][provider] = {'kind': 'deadline', 'message': 'Repository search budget exhausted.'}
                continue
            data, error = self._request(provider, record, doi, remaining)
            if error:
                report['errors'][provider] = error
                continue
            try:
                locations = (self._hal if provider == 'hal' else self._zenodo)(record, doi, data)
            except (ValueError, TypeError, AttributeError):
                report['errors'][provider] = {'kind': 'schema', 'message': 'Repository returned unexpected metadata.'}
                continue
            for item in locations:
                key = (item['url'], item['doi'], item['requires_selection'])
                if key not in seen:
                    seen.add(key)
                    report['alternatives' if item['requires_selection'] else 'locations'].append(item)
        report['status'] = ('found' if report['locations'] else 'alternatives' if report['alternatives']
                            else 'unavailable' if report['errors'] else 'not_found')
        return report
