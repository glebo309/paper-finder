"""Multi-source scholarly discovery with conservative, explainable identification.

Scores measure lexical evidence, not calibrated probabilities. A high provider rank
alone never establishes identity. Different DOIs are never silently merged, even
when preprint and published titles coincide. HTTP failures are reported separately
from successful empty searches; credentials and raw exception URLs are not returned.
"""
from difflib import SequenceMatcher
from html import unescape
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import math
import os
import re
import time
import threading
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlsplit

import requests

from .provider_limits import provider_cooldowns
from .discovery_cache import DiscoveryCache


_STOP = set('a an and as at by for from in into is of on or the to using via with'.split())
_ARXIV_LOCK = threading.Lock()
_SEMANTIC_LOCK = threading.Lock()
_SEMANTIC_NEXT_ALLOWED = 0.0
_DOI = re.compile(r'10\.\d{4,9}/[^\s<>"]+', re.I)


def _text(value):
    if not isinstance(value, str):
        return ''
    return unescape(re.sub(r'<[^>]*>', ' ', value)).strip()


def _normal(value):
    decomposed = unicodedata.normalize('NFKD', _text(value)).casefold()
    plain = ''.join(char for char in decomposed if not unicodedata.combining(char))
    return ' '.join(re.findall(r'[^\W_]+', plain, re.UNICODE))


def _doi(value):
    if isinstance(value, str) and value.startswith(('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/')):
        value = urlsplit(value).path
    decoded = unquote(value).strip().lstrip('/') if isinstance(value, str) else ''
    # DOI suffixes are opaque: legacy publisher identifiers legitimately contain
    # balanced angle brackets. Preserve these for explicit DOI values/URLs; the
    # conservative free-text extractor still stops at HTML delimiters.
    match = (re.fullmatch(r'10\.\d{4,9}/[^\s\"]+', decoded, re.I)
             if decoded.startswith('10.') else None) or _DOI.search(decoded)
    if not match:
        return None
    result = match.group(0).rstrip('.,;')
    while result.endswith(')') and result.count(')') > result.count('('):
        result = result[:-1]
    while result.endswith('>') and result.count('>') > result.count('<'):
        result = result[:-1]
    return result.lower()


def _year(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 1000 <= value <= 2200 else None


def _first(value):
    return _text(value[0]) if isinstance(value, list) and value else _text(value)


def _http(value):
    return value if isinstance(value, str) and value.startswith(('https://', 'http://')) else ''


def _record(source, title, doi=None, identifier=None, **fields):
    record = {'identifier': {'type': 'doi', 'value': doi} if doi else identifier or {'type': 'title', 'value': title},
              'doi': doi, 'title': _text(title), 'authors': [], 'year': None, 'journal': '',
              'abstract': '', 'metadata_source': source, 'sources': [source], 'score': 0.0,
              'match_reasons': [], 'url': 'https://doi.org/' + doi if doi else '', 'pdf_urls': []}
    record.update(fields)
    if record.get('record_type') in ('component', 'paratext'):
        record.setdefault('metadata_warnings', []).append('Supporting component; not a standalone paper. Manual review required.')
    return record


def _crossref(item):
    if not isinstance(item, dict):
        return None
    title = _first(item.get('title'))
    if not title:
        return None
    year = None
    for key in ('published', 'published-print', 'published-online', 'issued'):
        dates = (item.get(key) or {}).get('date-parts', [])
        if isinstance(dates, list) and dates and isinstance(dates[0], list) and dates[0]:
            year = _year(dates[0][0])
            if year:
                break
    authors = [' '.join(filter(None, [_text(a.get('given')), _text(a.get('family'))])) or _text(a.get('name'))
               for a in item.get('author', []) if isinstance(a, dict)]
    return _record('crossref', title, _doi(item.get('DOI')), authors=[a for a in authors if a], year=year,
                   journal=_first(item.get('container-title')), abstract=_text(item.get('abstract')),
                   publisher=_text(item.get('publisher')), record_type=_text(item.get('type')))


def _openalex(item):
    if not isinstance(item, dict):
        return None
    title = _text(item.get('display_name') or item.get('title'))
    if not title:
        return None
    work_id = _text(item.get('id')).rsplit('/', 1)[-1]
    authors = [_text((a.get('author') or {}).get('display_name')) for a in item.get('authorships', []) if isinstance(a, dict)]
    locations = list(item.get('locations') or [])
    for key in ('best_oa_location', 'primary_location'):
        if isinstance(item.get(key), dict):
            locations.append(item[key])
    indexed_locations = []
    version_reports = {}
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        pdf = _http(loc.get('pdf_url'))
        version = _text(loc.get('version')) or 'unknown'
        if pdf and version != 'unknown':
            version_reports.setdefault(pdf, set()).add(version)
        indexed_locations.append({'pdf_url': pdf or None,
            'landing_page_url': _http(loc.get('landing_page_url')) or None,
            'version': version, 'is_oa': loc.get('is_oa') is True,
            'license': _text(loc.get('license')) or None, 'source': 'openalex'})
    for loc in indexed_locations:
        conflicting = len(version_reports.get(loc['pdf_url'], set())) > 1
        loc['requires_selection'] = conflicting or loc['version'] == 'submittedVersion'
        loc['downloadable'] = bool(loc['pdf_url'] and loc['is_oa'] and not loc['requires_selection'])
        if conflicting:
            loc['version_conflict'] = True
    pdfs = list(dict.fromkeys(loc['pdf_url'] for loc in indexed_locations if loc['downloadable']))
    all_pdfs = list(dict.fromkeys(loc['pdf_url'] for loc in indexed_locations if loc['pdf_url']))
    record_urls = list(dict.fromkeys(_http(loc.get('landing_page_url')) for loc in locations
                                    if isinstance(loc, dict) and _http(loc.get('landing_page_url'))))
    arxiv_ids = []
    for url in record_urls + all_pdfs:
        parsed = urlsplit(url)
        if parsed.hostname in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
            match = re.fullmatch(r'/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?(?:\.pdf)?/?', parsed.path, re.I)
            if match and match.group(1) not in arxiv_ids:
                arxiv_ids.append(match.group(1))
    preprint_years = sorted({2000 + int(identifier[:2]) for identifier in arxiv_ids
                            if re.fullmatch(r'\d{4}\.\d{4,5}', identifier) and 1 <= int(identifier[2:4]) <= 12})
    citation_count = item.get('cited_by_count', 0)
    if not isinstance(citation_count, int) or isinstance(citation_count, bool) or citation_count < 0:
        citation_count = 0
    primary = item.get('primary_location') or {}
    location_dois = {_doi(loc.get('doi') or loc.get('landing_page_url')) for loc in locations if isinstance(loc, dict)} - {None}
    warnings = []
    if arxiv_ids and not primary.get('source') and len(location_dois) > 1:
        warnings.append('Unattributed primary DOI with multiple DOI locations; inspect the original repository record.')
    source = primary.get('source') or {}
    abstract = ''
    inverted = item.get('abstract_inverted_index')
    if isinstance(inverted, dict):
        positions = [(p, word) for word, indexes in inverted.items() if isinstance(word, str) and isinstance(indexes, list)
                     for p in indexes if isinstance(p, int) and 0 <= p < 20000]
        abstract = ' '.join(word for _, word in sorted(positions)[:20000])
    return _record('openalex', title, _doi(item.get('doi')),
                   identifier={'type': 'openalex', 'value': work_id} if work_id else None,
                   authors=[a for a in authors if a], year=_year(item.get('publication_year')),
                   journal=_text(source.get('display_name')), abstract=abstract,
                   url=_http(primary.get('landing_page_url')) or _http(item.get('doi')) or _http(item.get('id')),
                   pdf_urls=pdfs, record_urls=record_urls, indexed_locations=indexed_locations,
                   arxiv_ids=arxiv_ids, preprint_years=preprint_years,
                   cited_by_count=citation_count, metadata_warnings=warnings, record_type=_text(item.get('type')),
                   is_retracted=bool(item.get('is_retracted')))


def _scholar(item):
    if not isinstance(item, dict) or not _text(item.get('title')):
        return None
    external = item.get('externalIds') or {}
    identifier = {'type': 'arxiv', 'value': str(external['ArXiv'])} if external.get('ArXiv') else {'type': 'semanticscholar', 'value': _text(item.get('paperId'))}
    pdf = _http((item.get('openAccessPdf') or {}).get('url'))
    doi = _doi(external.get('DOI'))
    is_arxiv_pdf = bool(pdf and urlsplit(pdf).hostname in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'))
    preprint_is_requested = (not doi and identifier['type'] == 'arxiv') or bool(doi and doi.startswith('10.48550/arxiv.'))
    requires_selection = is_arxiv_pdf and bool(doi) and not preprint_is_requested
    indexed_locations = [{'pdf_url': pdf, 'landing_page_url': _http(item.get('url')) or None,
                          'version': 'submittedVersion' if is_arxiv_pdf else 'unknown',
                          'source': 'semanticscholar', 'is_oa': True, 'license': None,
                          'requires_selection': requires_selection,
                          'downloadable': not requires_selection}] if pdf else []
    return _record('semanticscholar', item['title'], doi, identifier=identifier,
                   authors=[_text(a.get('name')) for a in item.get('authors', []) if isinstance(a, dict)],
                   year=_year(item.get('year')), journal=_text(item.get('venue')), abstract=_text(item.get('abstract')),
                   url=_http(item.get('url')), pdf_urls=[pdf] if pdf and not requires_selection else [],
                   indexed_locations=indexed_locations, record_type='preprint' if preprint_is_requested else '')


def _europepmc(item):
    if not isinstance(item, dict) or not _text(item.get('title')):
        return None
    pmid = str(item.get('pmid') or (item.get('id') if item.get('source') == 'MED' else '') or '')
    pmid = pmid if re.fullmatch(r'\d+', pmid) else ''
    pmcid = _text(item.get('pmcid'))
    pmcid = pmcid if re.fullmatch(r'PMC\d+', pmcid) else ''
    source, source_id = _text(item.get('source')), _text(item.get('id'))
    identifier = ({'type': 'pmid', 'value': pmid} if pmid else
                  {'type': 'pmcid', 'value': pmcid} if pmcid else
                  {'type': 'europepmc', 'value': source + '/' + source_id} if source and source_id else None)
    authors = []
    for author in (item.get('authorList') or {}).get('author', []):
        if isinstance(author, dict):
            name = ' '.join(filter(None, [_text(author.get('firstName')), _text(author.get('lastName'))]))
            name = name or _text(author.get('fullName')) or _text(author.get('collectiveName'))
            if name:
                authors.append(name)
    if not authors:
        authors = [a.strip() for a in _text(item.get('authorString')).split(',') if a.strip()]
    links = (item.get('fullTextUrlList') or {}).get('fullTextUrl', [])
    pdfs = list(dict.fromkeys(_http(link.get('url')) for link in links
                             if isinstance(link, dict) and link.get('documentStyle', '').lower() == 'pdf'
                             and _http(link.get('url'))))
    journal = ((item.get('journalInfo') or {}).get('journal') or {})
    year_text = str(item.get('pubYear') or item.get('firstPublicationDate') or '')[:4]
    types = (item.get('pubTypeList') or {}).get('pubType', [])
    record = _record('europepmc', item['title'], _doi(item.get('doi')), identifier=identifier,
                    authors=authors, year=_year(int(year_text)) if year_text.isdigit() else None,
                    journal=_text(journal.get('title') or journal.get('medlineAbbreviation')),
                    abstract=_text(item.get('abstractText')), pmid=pmid, pmcid=pmcid,
                    publication_date=_text(item.get('firstPublicationDate')),
                    record_type='preprint' if source == 'PPR' or 'Preprint' in types else 'journal-article',
                    url='https://europepmc.org/article/' + quote(source, safe='') + '/' + quote(source_id, safe=''),
                    pdf_urls=pdfs, record_urls=[_http(link.get('url')) for link in links
                                              if isinstance(link, dict) and _http(link.get('url'))],
                    is_retracted=str(item.get('isRetracted', '')).upper() == 'Y' or 'Retracted Publication' in types)
    return record


def _arxiv_records(text, count):
    if not isinstance(text, str) or len(text) > 2_000_000 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Invalid Atom response')
    root = ET.fromstring(text)
    atom, arxiv = '{http://www.w3.org/2005/Atom}', '{http://arxiv.org/schemas/atom}'
    if root.tag != atom + 'feed':
        raise ValueError('Expected an Atom feed')
    records = []
    for entry in root.findall(atom + 'entry')[:count]:
        url = entry.findtext(atom + 'id', '')
        match = re.fullmatch(r'https?://arxiv.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z.-]+/\d{7}(?:v\d+)?)', url, re.I)
        if not match:
            raise ValueError('Invalid repository record')
        identifier = match.group(1)
        title = ' '.join(entry.findtext(atom + 'title', '').split())
        if not title:
            continue
        year = entry.findtext(atom + 'published', '')[:4]
        records.append(_record('arxiv', title, identifier={'type': 'arxiv', 'value': identifier},
                              authors=[_text(a.findtext(atom + 'name', '')) for a in entry.findall(atom + 'author')],
                              year=_year(int(year)) if year.isdigit() else None,
                              abstract=' '.join(entry.findtext(atom + 'summary', '').split()),
                              journal=_text(entry.findtext(arxiv + 'journal_ref', '')),
                              related_doi=_doi(entry.findtext(arxiv + 'doi', '')),
                              url='https://arxiv.org/abs/' + identifier,
                              pdf_urls=['https://arxiv.org/pdf/' + identifier], record_type='preprint',
                              arxiv_ids=[re.sub(r'v\d+$', '', identifier)],
                              source_ranks={'arxiv': len(records) + 1}))
    return records


def _deduplicate(records):
    merged = {}
    for record in records:
        identifier = record['identifier']
        # Only identical persistent identifiers prove two records are one work.
        # Title/year equality cannot distinguish preprints, corrections, or homonyms.
        key = ('doi', record['doi']) if record.get('doi') else (identifier['type'], identifier['value'])
        if identifier['type'] == 'title':
            key = ('title', _normal(record['title']), tuple(record['authors']), record['year'])
        if key not in merged:
            merged[key] = record
            continue
        target = merged[key]
        for name in ('sources', 'pdf_urls', 'record_urls', 'arxiv_ids', 'preprint_years', 'metadata_warnings'):
            target[name] = list(dict.fromkeys(target.get(name, []) + record.get(name, [])))
        for location in record.get('indexed_locations', []):
            if location not in target.setdefault('indexed_locations', []):
                target['indexed_locations'].append(location)
        for source, rank in record.get('source_ranks', {}).items():
            target.setdefault('source_ranks', {})[source] = min(rank, target.get('source_ranks', {}).get(source, rank))
        for name in ('authors', 'year', 'journal', 'abstract', 'url', 'publisher', 'record_type',
                     'pmid', 'pmcid', 'publication_date', 'related_doi'):
            if not target.get(name) and record.get(name):
                target[name] = record[name]
        target['cited_by_count'] = max(target.get('cited_by_count', 0), record.get('cited_by_count', 0))
        target['is_retracted'] = target.get('is_retracted', False) or record.get('is_retracted', False)
    for record in merged.values():
        excluded = {location.get('pdf_url') for location in record.get('indexed_locations', [])
                    if location.get('requires_selection') or location.get('downloadable') is False}
        if excluded:
            record['pdf_urls'] = [url for url in record.get('pdf_urls', []) if url not in excluded]
    return list(merged.values())


def _rank(query, record, exact_doi=None):
    if exact_doi:
        warnings = list(record.get('metadata_warnings') or [])
        if record.get('is_retracted'):
            warnings.append('Retracted work: manual review required')
        record.update(score=100.0, match_reasons=['Exact DOI match'] + warnings, _identity=not warnings)
        return
    query_norm, title = _normal(query), _normal(record['title'])
    query_words, title_words = set(query_norm.split()) - _STOP, set(title.split()) - _STOP
    overlap = len(query_words & title_words)
    precision = overlap / max(len(query_words), 1)
    recall = overlap / max(len(title_words), 1)
    similarity = SequenceMatcher(None, query_norm, title).ratio()
    reasons = []
    identity = False
    if query_norm == title:
        score, identity = 98.0, len(title_words) >= 4
        reasons.append('Exact normalized title')
    elif len(title_words) >= 3 and (' ' + title + ' ') in (' ' + query_norm + ' '):
        score, identity = 90.0, len(title_words) >= 4
        reasons.append('Full title occurs in citation')
    else:
        score = 65 * (2 * precision * recall / max(precision + recall, 0.001)) + 25 * similarity
        reasons.append(f'Title token overlap: {overlap}/{len(title_words)}')
        if similarity >= .92 and precision >= .8 and recall >= .8 and len(title_words) >= 4:
            score, identity = max(score, 90.0), True
            reasons.append('Near-exact title with minor spelling differences')
    years = {int(y) for y in re.findall(r'\b(?:18|19|20)\d{2}\b', query)}
    if years and record.get('year'):
        if record['year'] in years:
            score += 4
            reasons.append('Publication year matches')
        else:
            identity = False
            reasons.append('Publication year conflicts')
            if years & set(record.get('preprint_years', [])):
                score += 4
                reasons.append('Preprint submission year matches')
            else:
                score -= 20
    surnames = {_normal(a).split()[-1] for a in record['authors'] if _normal(a)}
    # Bibliographic text around a full title can carry authors before or after
    # the title. Known venue words and citation markers are not author claims.
    surrounding = ' '.join(query_norm.split(title, 1)) if title and title in query_norm else ''
    if years and surrounding:
        venue_words = set(_normal(record.get('journal', '')).split())
        names = ({w for w in surrounding.split() if len(w) > 1 and not w.isdigit()}
                 - _STOP - venue_words - {'et', 'al', 'eds', 'ed', 'vol', 'pp', 'pages', 'volume'})
        if names and surnames and not (names & surnames):
            score -= 20
            identity = False
            reasons.append('Citation author conflicts with indexed authors')
    if surnames & query_words:
        score += 5
        reasons.append('Author name matches')
    if (len(title_words) == 3 and title in query_norm and 'Publication year matches' in reasons
            and 'Author name matches' in reasons and not any('conflicts' in reason for reason in reasons)):
        identity = True
        score = max(score, 90)
        reasons.append('Short title corroborated by author and year')
    abstract_words = set(_normal(record.get('abstract', '')).split()) - _STOP
    if abstract_words and not identity:
        score += min(8, 8 * len(query_words & abstract_words) / max(len(query_words), 1))
    if (len(query_norm.split()) > max(24, 2 * len(title.split())) or
            re.search(r'\b(?:papers? (?:about|on|that)|i (?:remember|want|read|am)|find me|looking for|studies (?:about|on))\b', query, re.I)):
        identity = False
        score = min(score, 79)
        reasons.append('Descriptive query requires candidate selection')
    if set(record.get('source_ranks', {})) == {'openalex_semantic'}:
        identity = False
        reasons.append('Semantic retrieval alone requires candidate selection')
    if record.get('metadata_warnings'):
        identity = False
        reasons.extend(record['metadata_warnings'])
    if record.get('is_retracted'):
        identity = False
        reasons.append('Retracted work: manual review required')
    record.update(score=round(max(0, min(score, 100)), 2), match_reasons=reasons, _identity=identity)


def _citation_title(query):
    """Recover one explicit title, never invent keywords from descriptive prose.

    This only widens retrieval; all returned records are still scored against the
    complete original citation, including contradictory authors and years.
    """
    quoted = re.search(r'["“]([^"”]{20,300})["”]', query)
    if quoted:
        title = quoted.group(1).strip(' .')
    else:
        citation = re.match(r'^([^\d]{2,180}?)\s*\(?(?:18|19|20)\d{2}\)?[.:]?\s+(.+)$', query)
        if not citation:
            return None
        authors, remainder = citation.groups()
        words = _normal(authors).split()
        if any(word in {'paper', 'papers', 'study', 'studies', 'remember', 'find', 'about', 'that', 'by', 'in'} for word in words):
            return None
        if len(words) > 4 and not re.search(r'\bet\s+al\b|[,;]', authors, re.I):
            return None
        title = re.split(r'\.\s+', remainder, maxsplit=1)[0].strip(' ."“”')
    if len(_normal(title).split()) < 4 or _normal(title) == _normal(query):
        return None
    return title


class DiscoveryService:
    """Search independent indexes, rank evidence, and abstain on uncertain identity.

    ``providers`` optionally restricts sources (useful offline/testing). Requests are
    bounded by a per-call timeout and a total request budget. A 429 is not retried
    immediately: its Retry-After is exposed, and other indexes can still answer.
    """
    PROVIDERS = ('openalex', 'crossref', 'europepmc', 'semanticscholar', 'arxiv')

    def __init__(self, session=None, timeout=8, deadline=25, providers=None, cache=None, refresh=False):
        self.session = session or requests.Session()
        self.cache = cache if cache is not None else DiscoveryCache()
        self.refresh = bool(refresh)
        self._cache_hits = {}
        self.timeout = max(.1, float(timeout))
        self.deadline = max(.1, float(deadline))
        self.providers = tuple(providers) if providers is not None else self.PROVIDERS
        if any(p not in self.PROVIDERS for p in self.providers):
            raise ValueError('Unknown discovery provider')

    def _cached(self, provider, query, count, exact_doi):
        if self.refresh:
            return None
        hit = self.cache.get(provider, query, count, exact_doi=exact_doi)
        if hit is None:
            return None
        self._cache_hits[provider] = {key: hit[key] for key in ('age_seconds', 'expires_at')}
        return hit['records']

    def _fetch(self, provider, query, count, exact_doi, remaining, now=None):
        cached = self._cached(provider, query, count, exact_doi)
        if cached is not None:
            return cached, None
        cooldown = self.cache.cooldown_remaining(provider)
        if cooldown > 0:
            return [], {'kind': 'rate_limited', 'message': 'Metadata provider is cooling down; respect the retry interval.',
                        'retry_after': str(math.ceil(cooldown))}
        records, error = self._fetch_live(provider, query, count, exact_doi, remaining, now=now)
        if error and error.get('kind') == 'rate_limited':
            self.cache.set_cooldown(provider, provider_cooldowns._delay(error.get('retry_after')))
        elif not error:
            self.cache.put(provider, query, count, records, exact_doi=exact_doi)
        # The repository's mandatory request spacing also survives CLI restarts.
        if provider == 'arxiv':
            spacing = provider_cooldowns.remaining(provider, now=now)
            if spacing > 0:
                self.cache.set_cooldown(provider, spacing)
        return records, error

    def _fetch_live(self, provider, query, count, exact_doi, remaining, now=None):
        if provider == 'arxiv' and exact_doi:
            return [], None
        cooldown = provider_cooldowns.remaining(provider, now=now)
        if cooldown > 0:
            return [], {'kind': 'rate_limited', 'message': 'Metadata provider is cooling down; respect the retry interval.',
                        'retry_after': str(math.ceil(cooldown))}
        headers = {'User-Agent': 'PaperFinder/2 (scholarly metadata discovery)', 'Accept': 'application/json'}
        if provider in ('openalex', 'openalex_semantic', 'openalex_citation'):
            url = 'https://api.openalex.org/works'
            params = {'per_page': count, 'filter': 'doi:https://doi.org/' + exact_doi} if exact_doi else {'per_page': count, 'search': query}
            if provider == 'openalex_semantic':
                params = {'per_page': min(count, 50), 'search.semantic': query}
            if os.environ.get('OPENALEX_API_KEY'):
                headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
            parser, key = _openalex, 'results'
        elif provider == 'crossref':
            url = 'https://api.crossref.org/works' + ('/' + quote(exact_doi, safe='') if exact_doi else '')
            params = {} if exact_doi else {'query.bibliographic': query, 'rows': count}
            if os.environ.get('CROSSREF_MAILTO'):
                params['mailto'] = os.environ['CROSSREF_MAILTO']
            parser, key = _crossref, 'items'
        elif provider == 'europepmc':
            url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
            params = {'query': 'DOI:"' + exact_doi + '"' if exact_doi else (_citation_title(query) or query),
                      'format': 'json', 'resultType': 'core', 'pageSize': count}
            parser, key = _europepmc, 'result'
        elif provider == 'arxiv':
            with _ARXIV_LOCK:
                cooldown = provider_cooldowns.remaining('arxiv', now=now)
                if cooldown > 0:
                    return [], {'kind': 'rate_limited', 'message': 'Repository search is cooling down.',
                                'retry_after': str(math.ceil(cooldown))}
                provider_cooldowns.record_limit('arxiv', '3', now=now)
            title = _citation_title(query) or query
            words = re.findall(r'[^\W_]+', title, re.UNICODE)
            url = 'https://export.arxiv.org/api/query'
            params = {'search_query': 'ti:"' + ' '.join(words) + '"', 'start': 0,
                      'max_results': count, 'sortBy': 'relevance', 'sortOrder': 'descending'}
            headers['Accept'] = 'application/atom+xml'
        else:
            url = 'https://api.semanticscholar.org/graph/v1/paper/' + ('DOI:' + quote(exact_doi, safe='') if exact_doi else 'search')
            params = {'fields': 'title,authors,year,venue,abstract,externalIds,url,openAccessPdf'}
            if not exact_doi:
                params.update(query=query, limit=count)
            if os.environ.get('SEMANTIC_SCHOLAR_API_KEY'):
                headers['x-api-key'] = os.environ['SEMANTIC_SCHOLAR_API_KEY']
            parser, key = _scholar, 'data'
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=min(self.timeout, remaining))
        except requests.Timeout:
            return [], {'kind': 'timeout', 'message': 'Metadata provider timed out.'}
        except requests.RequestException:
            return [], {'kind': 'network_error', 'message': 'Metadata provider could not be reached.'}
        if response.status_code == 429:
            provider_cooldowns.record_limit(provider, response.headers.get('Retry-After'))
            return [], {'kind': 'rate_limited', 'message': 'Metadata provider rate limit reached.',
                        'retry_after': response.headers.get('Retry-After')}
        if response.status_code == 404 and exact_doi:
            return [], None
        if response.status_code in (401, 403):
            return [], {'kind': 'authentication', 'message': 'Provider denied access; check its optional API key and quota.'}
        if response.status_code != 200:
            return [], {'kind': 'http_error', 'message': f'Metadata provider returned HTTP {response.status_code}.'}
        try:
            if provider == 'arxiv':
                return _arxiv_records(response.text, count), None
            payload = response.json()
            if provider == 'crossref':
                payload = payload['message']
            if provider == 'europepmc':
                payload = payload['resultList']
            rows = [payload] if exact_doi and provider not in ('openalex', 'europepmc') else payload[key]
            if not isinstance(rows, list):
                raise ValueError('Expected a list')
            records = []
            for position, row in enumerate(rows[:count], 1):
                record = parser(row)
                if record:
                    record['source_ranks'] = {provider: position}
                    records.append(record)
            records = [r for r in records if r and (not exact_doi or r.get('doi') == exact_doi)]
            return records, None
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ET.ParseError):
            return [], {'kind': 'invalid_response', 'message': 'Metadata provider returned an unexpected schema.'}

    def search(self, query, limit=10, mode='identify'):
        if mode not in ('identify', 'discover'):
            raise ValueError('mode must be identify or discover')
        if not isinstance(query, str):
            raise ValueError('query must be text')
        limit = max(1, min(int(limit), 50))
        query = query.strip()
        self._cache_hits = {}
        result = {'query': query, 'status': 'not_found', 'candidates': [], 'selected': None, 'errors': {},
                  'cache': {'enabled': self.cache.enabled, 'refresh': self.refresh, 'hits': self._cache_hits}}
        if not query:
            return result
        if len(query) > 2000:
            raise ValueError('Query is too long; use a title, citation, or concise description (maximum 2000 characters).')
        exact_doi = _doi(query)
        start = time.monotonic()
        records, successes = [], 0
        remaining = self.deadline
        for provider in self.providers:
            if provider == 'arxiv':
                if exact_doi:
                    successes += 1
                    continue
                # Title/citation fallback only; no extra repository call for a
                # broad exploratory query or a confidently identified article.
                ranked = _deduplicate(records)
                for record in ranked:
                    _rank(query, record, exact_doi)
                ranked.sort(key=lambda r: r['score'], reverse=True)
                if self._match(ranked) or (len(self.providers) > 1 and
                        (mode == 'discover' or len(_normal(_citation_title(query) or query).split()) < 4)):
                    continue
            # Semantic Scholar is a fallback if the first two sources cannot securely identify.
            if provider == 'semanticscholar' and records and mode == 'identify':
                ranked = _deduplicate(records)
                for record in ranked:
                    _rank(query, record, exact_doi)
                ranked.sort(key=lambda r: r['score'], reverse=True)
                if self._match(ranked) and (exact_doi or not result['errors']):
                    records = ranked
                    continue
            remaining = self.deadline - (time.monotonic() - start)
            if remaining <= 0:
                result['errors'][provider] = {'kind': 'deadline', 'message': 'Search request budget exhausted.'}
                continue
            found, error = self._fetch(provider, query, max(10, limit), exact_doi, remaining, now=start + self.deadline - remaining)
            if error:
                result['errors'][provider] = error
            else:
                successes += 1
                records.extend(found)
        records = _deduplicate(records)
        for record in records:
            _rank(query, record, exact_doi)
        records.sort(key=lambda r: -r['score'])
        relaxed_title = _citation_title(query) if not exact_doi and not self._match(records) else None
        if relaxed_title and 'openalex' in self.providers and 'openalex' not in result['errors']:
            remaining = self.deadline - (time.monotonic() - start)
            if remaining <= 0:
                result['errors']['openalex_citation'] = {'kind': 'deadline', 'message': 'Search request budget exhausted.'}
            else:
                found, error = self._fetch('openalex_citation', relaxed_title, max(10, limit), None, remaining, now=start + self.deadline - remaining)
                if error:
                    result['errors']['openalex_citation'] = error
                else:
                    successes += 1
                    records.extend(found)
                    records = _deduplicate(records)
                    for record in records:
                        _rank(query, record, exact_doi)
                    records.sort(key=lambda r: -r['score'])
        if (not exact_doi and 'openalex' in self.providers and 'openalex' not in result['errors']
                and result['errors'].get('openalex_citation', {}).get('kind') not in ('rate_limited', 'authentication')
                and remaining > 0 and (mode == 'discover' or not self._match(records))):
            # A single additional semantic call, with a process-wide 1 rps guard.
            # Never sleep or immediately retry after exhausting a provider quota.
            global _SEMANTIC_NEXT_ALLOWED
            now = time.monotonic()
            remaining = self.deadline - (now - start)
            if remaining > 0:
                cached_semantic = self._cached('openalex_semantic', query, max(10, limit), None)
                with _SEMANTIC_LOCK:
                    allowed = cached_semantic is not None or now >= _SEMANTIC_NEXT_ALLOWED
                    if allowed and cached_semantic is None:
                        _SEMANTIC_NEXT_ALLOWED = now + 1.0
                if allowed:
                    if cached_semantic is not None:
                        found, error = cached_semantic, None
                    else:
                        found, error = self._fetch('openalex_semantic', query, max(10, limit), None, remaining, now=start + self.deadline - remaining)
                    if error:
                        result['errors']['openalex_semantic'] = error
                        if error.get('kind') == 'rate_limited':
                            retry = error.get('retry_after') or '1'
                            try:
                                delay = float(retry)
                            except (ValueError, TypeError):
                                try:
                                    delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                                except (ValueError, TypeError, OverflowError):
                                    delay = 1
                            with _SEMANTIC_LOCK:
                                _SEMANTIC_NEXT_ALLOWED = max(_SEMANTIC_NEXT_ALLOWED, time.monotonic() + max(1, delay))
                    else:
                        successes += 1
                        records.extend(found)
                else:
                    result['errors']['openalex_semantic'] = {
                        'kind': 'rate_limited', 'message': 'Semantic search is cooling down; respect the retry interval.',
                        'retry_after': str(max(1, math.ceil(_SEMANTIC_NEXT_ALLOWED - now)))}
        records = _deduplicate(records)
        for record in records:
            _rank(query, record, exact_doi)
            # Reciprocal-rank fusion keeps meaning-based retrieval useful even
            # when the best semantic match shares no literal query words.
            record['retrieval_score'] = round(sum((4 if source == 'openalex_semantic' else 1) / (1 + rank)
                for source, rank in record.get('source_ranks', {}).items()), 6)
        records.sort(key=lambda r: (-r['score'], r['title'].casefold(), str(r['identifier']['value'])))
        matched = mode == 'identify' and self._match(records) and (bool(exact_doi) or not result['errors'])
        if not exact_doi and result['errors']:
            for record in records:
                if record.get('_identity'):
                    record['match_reasons'].append('Provider coverage incomplete; manual selection required.')
        if not matched and any('openalex_semantic' in r.get('source_ranks', {}) for r in records):
            # Bibliographic evidence must survive semantic expansion. Meaning-only
            # ranking is useful for topic descriptions but cannot displace a close
            # title or the explicitly supplied author/year with a tangential hit.
            strong_title = any(r['score'] >= 70 for r in records)
            dated_query = bool(re.search(r'\b(?:18|19|20)\d{2}\b', query))
            def lexical_rank(record):
                return min((rank for source, rank in record.get('source_ranks', {}).items()
                            if source != 'openalex_semantic'), default=1000)
            if strong_title:
                records.sort(key=lambda r: (-r['score'], lexical_rank(r), -r['retrieval_score']))
            elif dated_query:
                records.sort(key=lambda r: (-(r['score'] + 12 * ('Author name matches' in r['match_reasons'])
                                                + 4 * ('Publication year matches' in r['match_reasons'])
                                                + min(12, 2 * math.log10(1 + r.get('cited_by_count', 0)))),
                                            lexical_rank(r), -r['retrieval_score']))
            else:
                records.sort(key=lambda r: (-r['retrieval_score'], -r['score']))
        if not matched:
            # Retain components for inspection, after standalone publications.
            # Do this after the identity decision so a figure's exact title never
            # makes a different, lower-scoring article an automatic selection.
            records.sort(key=lambda r: r.get('record_type') in ('component', 'paratext'))
        if records:
            result['status'] = 'matched' if matched else 'ambiguous'
            result['selected'] = records[0] if matched else None
            result['candidates'] = records[:limit]
        elif not successes:
            result['status'] = 'unavailable'
        for record in records:
            record.pop('_identity', None)
        return result

    @staticmethod
    def _match(records):
        return bool(records and records[0].get('_identity') and records[0]['score'] >= 90
                    and (len(records) == 1 or records[0]['score'] - records[1]['score'] >= 8))
