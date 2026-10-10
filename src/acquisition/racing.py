"""Operation-local discovery jobs for the first-verified-PDF race."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import threading

import requests

from src.core.pipeline import SourceMethod, operation_cancelled
from src.core.cancellation import CancellableSession
from .access_options import merge_access_reports
from .recent_open_access import RecentOpenAccessDiscovery, discover_landing_pdf
from .repository_discovery import RepositoryDiscovery


@contextmanager
def _session(original):
    # Requests sessions carry mutable cookies. Production routes own their own
    # sessions; injected transports are kept intact for deterministic tests.
    if not isinstance(original, requests.Session):
        yield original
        return
    with CancellableSession() as session:
        session.headers.update(original.headers)
        session.cookies.update(original.cookies)
        session.proxies.update(original.proxies)
        session.verify, session.cert = original.verify, original.cert
        session.trust_env = original.trust_env
        yield session


class DiscoveryRace:
    """Each provider discovers, downloads and checks candidates independently.

    Only the pipeline coordinator publishes a winning file. Reports are copied
    under a lock so late workers cannot mutate the returned result.
    """
    def __init__(self, finder, record, *, recent_sources=False, contact_email=None):
        self.finder = finder
        self.record = deepcopy(record)
        self.recent_sources = recent_sources
        self.doi = record.get('doi') or ((record.get('identifier') or {}).get('value')
            if (record.get('identifier') or {}).get('type') in {'doi', 'biorxiv', 'medrxiv'} else None)
        self.email = contact_email or getattr(getattr(finder.config, 'api', None), 'unpaywall_email', None)
        self.lock = threading.Lock()
        self.reports = {}
        self.attempts = {}
        self.winning_locations = {}
        self.sources = []
        known = [deepcopy(item) for item in record.get('indexed_locations', [])
                 if item.get('requires_selection') or item.get('version') in {'submittedVersion', 'conflicting'}]
        for item in known:
            item.update(requires_selection=True, downloadable=False)
        self.reports['indexed'] = {'alternatives': known}
        blocked = {item.get('pdf_url') for item in known}
        urls = list(record.get('pdf_urls') or [])
        if record.get('pdf_url'):
            urls.insert(0, record['pdf_url'])
        identifier = record.get('identifier') or {}
        kind, value = identifier.get('type'), identifier.get('value')
        if kind == 'arxiv':
            urls.append(f'https://arxiv.org/pdf/{value}')
        elif kind in {'biorxiv', 'medrxiv'}:
            urls.append(f'https://www.{kind}.org/content/{value}.full.pdf')
        urls = list(dict.fromkeys(url for url in urls if url not in blocked))
        if urls:
            self.sources.append(SourceMethod('Indexed PDF links', self._direct(urls), 'fast'))
        if recent_sources and self.doi:
            for provider, name in (('europepmc', 'Europe PMC discovery'), ('openalex', 'OpenAlex discovery'),
                                   ('unpaywall', 'Unpaywall discovery'), ('publisher', 'Publisher discovery'),
                                   ('hal', 'HAL repository'), ('zenodo', 'Zenodo repository')):
                self.sources.append(SourceMethod(name, self._discover(provider, name), 'medium'))

    def _download(self, name, target, urls, record, session, locations=()):
        if operation_cancelled():
            return False
        urls = [url for url in urls if not self._blocked(url)]
        if not urls:
            return False
        with tempfile.TemporaryDirectory(prefix='.paperfinder-route-', dir=Path(target).parent) as directory:
            result = self.finder._download_record_urls(record, urls, Path(directory), session=session)
            with self.lock:
                self.attempts.setdefault(name, {}).update(result.attempts or {})
            if not result.success or operation_cancelled():
                return False
            verified_urls = [url for url, status in result.attempts.items() if status == 'verified']
            if any(self._blocked(url) for url in verified_urls):
                with self.lock:
                    for url in verified_urls:
                        self.attempts[name][url] = 'version requires selection'
                return False
            shutil.copyfile(result.filepath, target)
            with self.lock:
                for location in locations:
                    if result.attempts.get(location.get('pdf_url')) == 'verified':
                        self.winning_locations[name] = deepcopy(location)
                        break
            return True

    def _blocked(self, url):
        with self.lock:
            access = merge_access_reports(*self.reports.values())
        def matches(item):
            return url in {item.get('pdf_url'), item.get('url'), item.get('landing_page_url')}
        if any(matches(item) for item in access.get('alternatives', [])):
            return True
        # Access labels can be stale. A separately reported open copy may be
        # attempted and verified without overriding manuscript-version evidence.
        if any(matches(item) and item.get('availability') == 'open'
               for item in access.get('locations', [])):
            return False
        return any(matches(item) for group in ('embargoed', 'closed') for item in access.get(group, []))

    def _direct(self, urls):
        def run(doi, target, metadata):
            record = deepcopy(metadata)
            if self.recent_sources and self.doi:
                record['verification_policy'] = {'require_identifier': True}
            with _session(self.finder.session) as session:
                return self._download('Indexed PDF links', target, urls, record, session)
        return run

    def _discover(self, provider, name):
        def run(doi, target, metadata):
            with _session(self.finder.session) as session:
                try:
                    if provider in RepositoryDiscovery.PROVIDERS:
                        report = RepositoryDiscovery(session=session, providers=[provider]).discover(deepcopy(metadata))
                    else:
                        report = RecentOpenAccessDiscovery(session=session, email=self.email,
                            providers=[provider], publisher_fallback=False).discover(doi)
                except Exception:
                    report = {'errors': {provider: {'kind': 'error', 'message': 'Source discovery failed.'}}}
                if operation_cancelled():
                    return False
                report = merge_access_reports(report, self.reports['indexed'])
                with self.lock:
                    self.reports[name] = deepcopy(report)
                # Each provider owns its landing-page budget. No other strategy
                # waits for a slow redirect or a missing index response.
                for location in report.get('locations', [])[:5]:
                    if operation_cancelled():
                        return False
                    if not location.get('downloadable') and location.get('availability') == 'open':
                        try:
                            location = discover_landing_pdf(location, session=session, timeout=5) or location
                        except Exception:
                            continue
                    if not location.get('downloadable') or not location.get('pdf_url'):
                        continue
                    record = deepcopy(metadata)
                    # An unclassified file cannot win by title similarity while
                    # another route is still determining publication versions.
                    if location.get('version') not in {'acceptedVersion', 'publishedVersion'}:
                        record['verification_policy'] = {'require_identifier': True}
                    if self._download(name, target, [location['pdf_url']], record, session, [location]):
                        return True
                return False
        return run

    def finish(self, result):
        with self.lock:
            metadata = deepcopy(self.record)
            metadata['access_options'] = merge_access_reports(*self.reports.values())
            metadata['candidate_attempts'] = deepcopy(self.attempts)
            for attempts in self.attempts.values():
                result.attempts.update(deepcopy(attempts))
            if result.source in self.winning_locations:
                metadata['fulltext_location'] = deepcopy(self.winning_locations[result.source])
        return metadata


def acquire_record_race(finder, record, output_dir, *, recent_sources=False, contact_email=None):
    race = DiscoveryRace(finder, record, recent_sources=recent_sources, contact_email=contact_email)
    excluded = ('Unpaywall', 'Europe PMC', 'Open Access (Browser)') if recent_sources else ()
    if not race.doi:
        excluded = tuple(source.name for source in finder.pipeline.sources)
    policies = {source.name: {'require_identifier': True} for source in finder.pipeline.sources}
    if not (recent_sources and race.doi):
        policies = {}
    output = finder._available_output(Path(output_dir), record['identifier']['value'])
    result = finder.pipeline.execute(race.doi or '', output, deepcopy(record),
        additional_sources=race.sources, exclude_sources=excluded, verification_policies=policies,
        progress_callback=lambda stage, message: print(f"{stage}: {message}"))
    metadata = race.finish(result)
    return finder._verify_result(result, metadata)
