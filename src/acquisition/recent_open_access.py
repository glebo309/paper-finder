"""Discover current full-text locations without silently substituting versions.

This is metadata discovery, not a downloader or a permission inference engine.
A free-to-read location may have no known reuse license. A PDF is still subject
 to document identity verification by the acquisition coordinator.
"""
import math
import os
import re
import time
from urllib.parse import quote, unquote, urlsplit

import requests

from src.core import provider_limits
from src.core.discovery import _doi as normalize_doi
from src.core.discovery_cache import DiscoveryCache


def _doi(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.match(r'^https?://(?:dx\.)?doi\.org/', value, re.I):
        value = urlsplit(value).path.lstrip('/')
    else:
        value = re.sub(r'^doi:\s*', '', value, flags=re.I)
    value = unquote(value)
    # Only explicit identifiers enter exact-DOI APIs. Unlike a free-text query,
    # an opaque legacy DOI may contain balanced angle brackets and parentheses.
    if not re.fullmatch(r'10\.\d{4,9}/[^\s"]+', value, re.I):
        return None
    return normalize_doi(value)


def _url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not (parsed.username or parsed.password):
            return value
    except ValueError:
        pass
    return None


def _objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _is_preprint(record):
    publication_types = record.get('pubTypeList')
    types = publication_types.get('pubType', []) if isinstance(publication_types, dict) else []
    return record.get('source') == 'PPR' or any(
        isinstance(value, str) and value.casefold() == 'preprint'
        for value in (types if isinstance(types, list) else []))


def _location(provider, doi, pdf=None, landing=None, version=None, license=None,
              host_type=None, availability='open', available_from=None):
    pdf, landing = _url(pdf), _url(landing)
    if not pdf and not landing:
        return None
    version = version if version in ('publishedVersion', 'acceptedVersion', 'submittedVersion') else 'unknown'
    return {
        'doi': doi, 'url': pdf or landing, 'pdf_url': pdf, 'landing_page_url': landing,
        'version': version, 'license': license if isinstance(license, str) else None,
        'host_type': host_type or 'unknown', 'source': provider, 'sources': [provider],
        'availability': availability, 'available_from': available_from,
        'requires_selection': version == 'submittedVersion',
        'downloadable': bool(pdf and availability == 'open'),
        'provenance': [{'provider': provider, 'doi': doi, 'version': version,
                        'license': license, 'availability': availability}],
    }


class RecentOpenAccessDiscovery:
    """Look up all available copies of one DOI using bounded API requests.

    `locations` contains available published, accepted, or unknown-version
    locations; `alternatives` contains submitted versions and conflicting
    version reports and requires explicit user selection. `embargoed` and
    `closed` are informational only. Landing pages have downloadable=False.
    Provider failures are reported in `errors` separately from missing copies.
    Only provider cooldowns are persisted; full-text locations are freshly fetched. The public APIs may not yet have indexed very recent deposits.
    """
    PROVIDERS = ('europepmc', 'unpaywall', 'openalex')

    def __init__(self, session=None, timeout=8, deadline=20, providers=None, email=None, cache=None, publisher_fallback=True):
        self.session = session or requests.Session()
        self.cache = cache if cache is not None else DiscoveryCache()
        self.timeout = max(.1, float(timeout))
        self.deadline = max(.1, float(deadline))
        self.providers = tuple(providers) if providers is not None else self.PROVIDERS
        if any(provider not in self.PROVIDERS for provider in self.providers):
            raise ValueError('Unknown full-text location provider')
        self.email = email if email is not None else os.environ.get('UNPAYWALL_EMAIL')
        self.publisher_fallback = bool(publisher_fallback)

    def _request(self, provider, doi, remaining):
        delay = max(provider_limits.remaining(provider), self.cache.cooldown_remaining(provider))
        if delay:
            self.cache.set_cooldown(provider, delay)
            return None, {'kind': 'rate_limited', 'message': 'Provider is cooling down.', 'retry_after': math.ceil(delay)}
        headers = {'User-Agent': 'PaperFinder/2 (full-text location discovery)', 'Accept': 'application/json'}
        if provider == 'unpaywall':
            if not self.email or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.email) or self.email.lower() == 'test@test.com':
                return None, {'kind': 'not_configured', 'message': 'Set UNPAYWALL_EMAIL to your contact email to enable Unpaywall.'}
            url = 'https://api.unpaywall.org/v2/' + quote(doi, safe='')
            params = {'email': self.email}
        elif provider == 'openalex':
            url = 'https://api.openalex.org/works/https://doi.org/' + quote(doi, safe='')
            params = {}
            if os.environ.get('OPENALEX_API_KEY'):
                headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
        else:
            url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
            params = {'query': 'DOI:"' + doi + '"', 'format': 'json', 'resultType': 'core', 'pageSize': 10}
        response = None
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=min(self.timeout, remaining))
            if response.status_code == 429:
                delay = provider_limits.record_limit(provider, response.headers.get('Retry-After'))
                self.cache.set_cooldown(provider, delay)
                return None, {'kind': 'rate_limited', 'message': 'Provider rate limit reached.', 'retry_after': math.ceil(delay)}
            if response.status_code == 404:
                return {}, None
            if response.status_code in (401, 403):
                return None, {'kind': 'authentication', 'message': 'Provider denied this request; check API access settings.'}
            if response.status_code != 200:
                return None, {'kind': 'http', 'message': f'Provider returned HTTP {response.status_code}.'}
            data = response.json()
            if not isinstance(data, dict):
                return None, {'kind': 'schema', 'message': 'Provider returned an unexpected metadata format.'}
            return data, None
        except requests.Timeout:
            return None, {'kind': 'timeout', 'message': 'Full-text metadata provider timed out.'}
        except requests.RequestException:
            return None, {'kind': 'network', 'message': 'Full-text metadata provider could not be reached.'}
        except (ValueError, TypeError):
            return None, {'kind': 'schema', 'message': 'Provider returned invalid metadata.'}
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _parse(provider, doi, data):
        locations = []
        if provider in ('unpaywall', 'openalex'):
            if data and _doi(data.get('doi')) != doi:
                return [], {'kind': 'identity_mismatch', 'message': 'Provider response did not confirm the requested DOI.'}
            if provider == 'unpaywall':
                for field, availability in (('oa_locations', 'open'), ('oa_locations_embargoed', 'embargoed')):
                    for item in _objects(data.get(field)):
                        locations.append(_location(provider, doi, pdf=item.get('url_for_pdf'),
                            landing=item.get('url_for_landing_page') or item.get('url'),
                            version=item.get('version'), license=item.get('license'),
                            host_type=item.get('host_type'), availability=availability,
                            available_from=item.get('oa_date') if availability == 'embargoed' else None))
            else:
                for item in _objects(data.get('locations')):
                    source = item.get('source') if isinstance(item.get('source'), dict) else {}
                    host_type = 'repository' if source.get('type') == 'repository' else 'publisher' if source.get('type') in ('journal', 'conference', 'book series') else 'unknown'
                    locations.append(_location(provider, doi, pdf=item.get('pdf_url'),
                        landing=item.get('landing_page_url'), version=item.get('version'),
                        license=item.get('license'), host_type=host_type,
                        availability='open' if item.get('is_oa') is True else 'closed'))
        else:
            result_list = data.get('resultList')
            if result_list is not None and not isinstance(result_list, dict):
                return [], {'kind': 'schema', 'message': 'Provider returned an unexpected metadata format.'}
            for record in _objects((result_list or {}).get('result')):
                if _doi(record.get('doi')) != doi:
                    continue
                url_list = record.get('fullTextUrlList')
                if not isinstance(url_list, dict):
                    continue
                for item in _objects(url_list.get('fullTextUrl')):
                    is_pdf = str(item.get('documentStyle', '')).lower() == 'pdf'
                    version = 'submittedVersion' if _is_preprint(record) else None
                    locations.append(_location(provider, doi, pdf=item.get('url') if is_pdf else None,
                        landing=item.get('url') if not is_pdf else None, version=version,
                        license=record.get('license'),
                        availability='open' if item.get('availabilityCode') in ('OA', 'F') else 'closed'))
        return [item for item in locations if item], None

    def discover(self, doi):
        """Return locations, alternatives, closed/embargoed copies, and errors."""
        normalized = _doi(doi)
        result = {'doi': normalized, 'status': 'invalid' if not normalized else 'not_found',
                  'locations': [], 'alternatives': [], 'embargoed': [], 'closed': [], 'errors': {}}
        if not normalized:
            return result
        start = time.monotonic()
        merged = {}
        succeeded = 0
        for provider in self.providers:
            remaining = self.deadline - (time.monotonic() - start)
            if remaining <= 0:
                result['errors'][provider] = {'kind': 'deadline', 'message': 'Full-text discovery time budget exhausted.'}
                continue
            data, error = self._request(provider, normalized, remaining)
            if error:
                result['errors'][provider] = error
                continue
            locations, error = self._parse(provider, normalized, data)
            if error:
                result['errors'][provider] = error
                continue
            succeeded += 1
            if provider == 'europepmc':
                from src.acquisition.pmc_cloud import discover_pmc_cloud
                records = (data.get('resultList') or {}).get('result', [])
                checked_pmcids = set()
                for record in _objects(records):
                    pmcid = record.get('pmcid')
                    if (_doi(record.get('doi')) != normalized or record.get('isOpenAccess') != 'Y'
                            or not isinstance(pmcid, str) or not re.fullmatch(r'PMC\d+', pmcid)
                            or pmcid in checked_pmcids or len(checked_pmcids) >= 2):
                        continue
                    remaining = self.deadline - (time.monotonic() - start)
                    if remaining <= 0:
                        break
                    checked_pmcids.add(pmcid)
                    cloud = discover_pmc_cloud(pmcid, normalized, session=self.session,
                        timeout=self.timeout, deadline=remaining, cache=self.cache)
                    result['errors'].update(cloud['errors'])
                    for copy in cloud['locations']:
                        version = 'submittedVersion' if _is_preprint(record) else copy['version']
                        item = _location('pmc_cloud', normalized, pdf=copy['pdf_url'],
                            landing='https://pmc.ncbi.nlm.nih.gov/articles/' + pmcid + '/',
                            version=version, license=copy['license'], host_type='repository')
                        if item:
                            item['pmcid'] = pmcid
                            item['pmc_version'] = copy.get('pmc_version')
                            item['provenance'][0]['metadata_url'] = copy['metadata_url']
                            item['provenance'][0]['attribution'] = 'US National Library of Medicine, PMC Article Datasets'
                            locations.append(item)
            for item in locations:
                # The same URL can legitimately be reported open by one index
                # and embargoed by another; retain both access observations.
                key = (item['url'], item['availability'])
                prior = merged.get(key)
                if not prior:
                    merged[key] = item
                    continue
                prior['sources'] = list(dict.fromkeys(prior['sources'] + item['sources']))
                prior['provenance'].extend(item['provenance'])
                if prior['version'] == 'unknown':
                    prior['version'] = item['version']
                elif item['version'] not in ('unknown', prior['version']):
                    prior['version'] = 'conflicting'
                prior['requires_selection'] = prior['version'] in ('submittedVersion', 'conflicting')
                prior['license'] = prior['license'] or item['license']
                prior['landing_page_url'] = prior['landing_page_url'] or item['landing_page_url']
        # Indexes can lag behind a publisher's own access declaration. Inspect
        # the canonical DOI landing page once, only when no usable main-article
        # PDF has been located, sharing the overall discovery time budget.
        if self.publisher_fallback and not any(item.get('availability') == 'open'
                and item.get('downloadable') and not item.get('requires_selection') for item in merged.values()):
            remaining = self.deadline - (time.monotonic() - start)
            if remaining <= 0:
                result['errors']['publisher'] = {'kind': 'deadline', 'message': 'Publisher access check skipped because the discovery time budget was exhausted.'}
            else:
                from src.acquisition.publisher_access import discover_publisher_access
                publisher = discover_publisher_access(normalized, session=self.session,
                    timeout=min(self.timeout, remaining), max_requests=5)
                result['publisher_access'] = publisher
                messages = {
                    'blocked': 'Publisher blocked automated access. This does not establish that the article is closed.',
                    'identity_mismatch': 'Publisher landing-page metadata did not confirm the requested DOI.',
                    'unavailable': 'Publisher access metadata could not be retrieved within this request.',
                }
                errors = publisher.get('errors') or {}
                if publisher.get('status') in messages:
                    error = dict(errors.get('publisher') or {'kind': publisher['status']})
                    error.setdefault('message', messages[publisher['status']])
                    result['errors']['publisher'] = error
                for item in publisher.get('locations', []):
                    if item.get('doi') == normalized and item.get('availability') == 'open':
                        # Retain stale closed observations separately from new
                        # publisher evidence; never rewrite history as agreement.
                        key = (item['url'], item['availability'])
                        if key not in merged:
                            merged[key] = item
                        else:
                            prior = merged[key]
                            prior['sources'] = list(dict.fromkeys(prior['sources'] + item['sources']))
                            prior['provenance'].extend(item['provenance'])
                            prior['license'] = prior['license'] or item['license']
                if publisher.get('status') in ('found', 'closed', 'unknown'):
                    succeeded += 1
        for item in merged.values():
            destination = 'embargoed' if item['availability'] == 'embargoed' else 'closed' if item['availability'] == 'closed' else 'alternatives' if item['requires_selection'] else 'locations'
            result[destination].append(item)
        priority = {'publishedVersion': 0, 'acceptedVersion': 1, 'unknown': 2}
        result['locations'].sort(key=lambda item: (priority.get(item['version'], 3), not item['downloadable']))
        if result['locations']:
            result['status'] = 'found'
        elif result['alternatives']:
            result['status'] = 'alternatives'
        elif not succeeded:
            result['status'] = 'unavailable'
        return result


def discover_landing_pdf(location, session=None, timeout=5, max_bytes=1024 * 1024):
    """Resolve one open landing page's explicit main-article PDF advertisement.

    Reads at most one bounded HTML document (up to three redirect hops), never
    downloads a PDF body, and does not click links, authenticate, or solve
    challenges. A successful location still requires normal PDF verification.
    Input metadata is preserved; the supplied dictionary is never modified.
    """
    from copy import deepcopy
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    if (location.get('availability') != 'open' or location.get('requires_selection')
            or not _url(location.get('landing_page_url'))):
        return None
    session = session or requests.Session()
    current = location['landing_page_url']
    deadline = time.monotonic() + max(.1, float(timeout))

    class CitationParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.links, self.dois, self.title = [], [], []
            self.in_title = False

        def handle_starttag(self, tag, attrs):
            attrs = {key.lower(): value or '' for key, value in attrs}
            name = (attrs.get('name') or attrs.get('property') or '').lower()
            if tag == 'title':
                self.in_title = True
            if tag == 'meta' and name == 'citation_doi':
                self.dois.append(attrs.get('content', ''))
            if tag == 'meta' and name == 'citation_pdf_url':
                self.links.append((attrs.get('content', ''), attrs.get('title', '')))
            if (tag == 'link' and 'alternate' in attrs.get('rel', '').lower().split()
                    and attrs.get('type', '').lower().split(';')[0] == 'application/pdf'):
                self.links.append((attrs.get('href', ''), attrs.get('title', '')))

        def handle_endtag(self, tag):
            if tag == 'title':
                self.in_title = False

        def handle_data(self, data):
            if self.in_title:
                self.title.append(data)

    def resolved(pdf, landing):
        result = deepcopy(location)
        result.update(url=pdf, pdf_url=pdf, landing_page_url=landing, downloadable=True)
        result.setdefault('provenance', []).append({'provider': 'landing_page', 'url': landing,
                                                   'evidence': 'advertised_pdf'})
        return result

    for hop in range(4):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        response = None
        try:
            response = session.get(current, stream=True, allow_redirects=False, timeout=remaining,
                                   headers={'User-Agent': 'PaperFinder/2 (open full-text discovery)'})
            headers = {key.lower(): value for key, value in response.headers.items()}
            if response.status_code in (301, 302, 303, 307, 308):
                current = _url(urljoin(current, headers.get('location', '')))
                if not current or hop == 3:
                    return None
                continue
            if response.status_code != 200:
                return None
            final_url = _url(response.url) or current
            content_type = str(headers.get('content-type', '')).lower().split(';')[0].strip()
            if content_type == 'application/pdf':
                return resolved(final_url, location['landing_page_url'])
            if content_type not in ('text/html', 'application/xhtml+xml'):
                return None
            if headers.get('content-length') and int(headers['content-length']) > max_bytes:
                return None
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if time.monotonic() >= deadline or len(body) + len(chunk) > max_bytes:
                    return None
                body.extend(chunk)
            parser = CitationParser()
            parser.feed(body.decode('utf-8', errors='replace'))
            page_title = ' '.join(parser.title).lower()
            if re.search(r'captcha|verify you are human|access denied|just a moment|sign[ -]?in|log[ -]?in', page_title):
                return None
            expected = _doi(location.get('doi'))
            if expected and any(_doi(value) != expected for value in parser.dois):
                return None
            for href, label in parser.links:
                if re.search(r'supplement|supporting information', label, re.I):
                    continue
                pdf_url = _url(urljoin(final_url, href)) if href else None
                if pdf_url:
                    return resolved(pdf_url, final_url)
            return None
        except (requests.RequestException, ValueError, TypeError):
            return None
        finally:
            if response is not None:
                response.close()
    return None
