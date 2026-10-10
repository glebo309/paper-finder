"""Official PMC Article Datasets, using the August 2026 cloud structure.

Metadata and PDF locations are provided by the US National Library of Medicine.
See https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/ and the bucket's README.txt.
The retired oa.fcgi/FTP package service is not used.
"""
import json
import math
import re
import time
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import requests
from src.core.cancellation import CancellableSession

from src.core import provider_limits
from src.core.discovery import _doi
from src.core.discovery_cache import DiscoveryCache

BASE = 'https://pmc-oa-opendata.s3.amazonaws.com/'


def discover_pmc_cloud(pmcid, doi, session=None, timeout=8, deadline=12,
                       max_bytes=1024 * 1024, cache=None):
    """Resolve up to five real article versions, returning metadata only.

    The supplied PMCID must already belong to the requested DOI. Each cloud
    metadata record confirms that binding again. Main PDF URLs come solely from
    the record's pdf_url, never filenames, supplementary lists, or guessed paths.
    """
    output = {'locations': [], 'errors': {}}
    if not isinstance(pmcid, str) or not re.fullmatch(r'PMC\d+', pmcid) or not _doi(doi):
        output['errors']['pmc_cloud'] = {'kind': 'invalid', 'message': 'A confirmed PMCID and DOI are required.'}
        return output
    doi = _doi(doi)
    session = session or CancellableSession()
    cache = cache if cache is not None else DiscoveryCache()
    end = time.monotonic() + max(.1, float(deadline))

    def error(kind, message, **extra):
        output['errors']['pmc_cloud'] = {'kind': kind, 'message': message, **extra}

    def fetch(url, params=None):
        remaining = end - time.monotonic()
        if remaining <= 0:
            error('deadline', 'PMC cloud request budget exhausted.')
            return None
        delay = max(provider_limits.remaining('pmc_cloud'), cache.cooldown_remaining('pmc_cloud'))
        if delay:
            error('rate_limited', 'PMC cloud is cooling down.', retry_after=math.ceil(delay))
            return None
        response = None
        try:
            response = session.get(url, params=params, timeout=min(max(.1, timeout), remaining), stream=True,
                                   headers={'User-Agent': 'PaperFinder/2 (NLM PMC dataset discovery)'})
            if response.status_code == 429:
                delay = provider_limits.record_limit('pmc_cloud', response.headers.get('Retry-After'))
                cache.set_cooldown('pmc_cloud', delay)
                error('rate_limited', 'PMC cloud rate limit reached.', retry_after=math.ceil(delay))
                return None
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                error('http', f'PMC cloud returned HTTP {response.status_code}.')
                return None
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if time.monotonic() >= end:
                    error('deadline', 'PMC cloud request budget exhausted.')
                    return None
                if len(body) + len(chunk) > max_bytes:
                    error('size', 'PMC cloud metadata exceeded the size limit.')
                    return None
                body.extend(chunk)
            return bytes(body)
        except requests.Timeout:
            error('timeout', 'PMC cloud metadata request timed out.')
        except requests.RequestException:
            error('network', 'PMC cloud metadata could not be reached.')
        finally:
            if response is not None:
                response.close()
        return None

    raw = fetch(BASE, {'list-type': '2', 'prefix': 'metadata/' + pmcid + '.', 'max-keys': 6})
    if raw is None:
        return output
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        error('schema', 'PMC cloud returned invalid listing metadata.')
        return output
    keys = [node.text for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'Key'
            and isinstance(node.text, str) and re.fullmatch(r'metadata/' + pmcid + r'\.\d+\.json', node.text)]
    if len(keys) > 5 or any(node.text == 'true' for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'IsTruncated'):
        error('partial', 'PMC cloud has more versions than this bounded lookup can inspect.')
    for key in keys[:5]:
        metadata_url = BASE + quote(key, safe='/')
        raw = fetch(metadata_url)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            error('schema', 'PMC cloud returned invalid article metadata.')
            continue
        if not isinstance(data, dict) or data.get('pmcid') != pmcid or _doi(data.get('doi')) != doi:
            error('identity_mismatch', 'PMC cloud record did not confirm the requested PMCID and DOI.')
            continue
        if data.get('is_pmc_openaccess') not in (True, 'yes') or data.get('is_retracted') in (True, 'yes'):
            continue
        pdf = data.get('pdf_url')
        if not isinstance(pdf, str):
            continue
        try:
            parsed = urlsplit(pdf)
            if parsed.scheme != 's3' or parsed.netloc != 'pmc-oa-opendata':
                continue
            version_prefix = key.removeprefix('metadata/').removesuffix('.json')
            if not parsed.path.startswith('/' + version_prefix + '/') or '..' in parsed.path.split('/'):
                continue
            # s3://bucket/key and bucket's documented HTTPS URL name the same
            # public object. The checksum query is metadata, not authentication.
            pdf_url = BASE + parsed.path.lstrip('/') + ('?' + parsed.query if parsed.query else '')
        except ValueError:
            continue
        manuscript = data.get('is_manuscript')
        version = 'acceptedVersion' if manuscript in (True, 'yes') else 'publishedVersion' if manuscript in (False, 'no') else 'unknown'
        output['locations'].append({'pdf_url': pdf_url, 'version': version,
            'license': data.get('license_code'), 'pmcid': pmcid, 'metadata_url': metadata_url,
            'pmc_version': data.get('version'), 'source': 'pmc_cloud'})
    return output
