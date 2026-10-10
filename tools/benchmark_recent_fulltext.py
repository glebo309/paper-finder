#!/usr/bin/env python3
"""Opt-in recent full-text smoke benchmark, restricted to explicit OA routes.

Default: show cases without network access. --live: metadata locations only.
--live --download --download-dir /tmp/paper-finder-recent: fetch eligible PDFs,
verify their identities, and retain them in the chosen temporary directory.
This curated three-case sample is not an estimate of general retrieval success.
No legacy acquisition routes or messaging services are invoked.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / 'tests' / 'fixtures' / 'recent_fulltext_cases.json'


def load_cases(path):
    payload = json.loads(Path(path).read_text())
    cases = payload.get('cases') if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError('Expected nonempty case list')
    seen = set()
    for case in cases:
        record = case['record']
        if not case.get('id') or case['id'] in seen:
            raise ValueError('Case IDs must be unique')
        seen.add(case['id'])
        if not re.fullmatch(r'10\.\d{4,9}/\S+', record.get('doi', '')) or not record.get('title'):
            raise ValueError('Each case requires DOI and title')
        date.fromisoformat(record['publication_date'])
        if record.get('identifier') != {'type': 'doi', 'value': record['doi']}:
            raise ValueError('Case DOI and canonical identifier disagree')
    return cases


def _download(record, urls, directory):
    """Use only the production direct-PDF coordinator, with no source registry."""
    from types import SimpleNamespace
    import requests
    from paper_finder import PaperFinder
    finder = PaperFinder.__new__(PaperFinder)
    finder.config = SimpleNamespace(validation=SimpleNamespace(max_size_mb=100))
    finder.session = requests.Session()
    finder._cancel_requested = False
    try:
        return finder._download_record_urls(record, urls, directory)
    finally:
        finder.session.close()


def _landing(location):
    from src.acquisition.recent_open_access import discover_landing_pdf
    resolved = discover_landing_pdf(location, timeout=5)
    return {'status': 'located' if resolved else 'not_found',
            'pdf_urls': [resolved['pdf_url']] if resolved and resolved.get('pdf_url') else [],
            'location': resolved}


def run_cases(cases, service, *, download=False, download_dir=None,
              downloader=None, landing_resolver=None):
    if download and download_dir is None:
        raise ValueError('Downloading requires an explicit temporary output directory')
    directory = Path(download_dir) if download_dir is not None else None
    if download:
        directory.mkdir(parents=True, exist_ok=True)
    rows = []
    today = datetime.now(timezone.utc).date()
    for case in cases:
        start = time.monotonic()
        record = case['record']
        discovery = service.discover(record['doi'])
        metadata_seconds = time.monotonic() - start
        row = {'id': case['id'], 'cohort': case.get('cohort'), 'doi': record['doi'],
               'title': record['title'], 'publication_date': record['publication_date'],
               'age_days': (today - date.fromisoformat(record['publication_date'])).days,
               'metadata_status': discovery.get('status'),
               'provider_errors': discovery.get('errors', {}),
               'metadata_seconds': round(metadata_seconds, 3), 'download_seconds': 0.0,
               'locations': discovery.get('locations', []), 'alternatives': discovery.get('alternatives', []),
               'embargoed': discovery.get('embargoed', []), 'closed': discovery.get('closed', []),
               'pdf_bytes': 0, 'filepath': None, 'verification': None, 'attempts': {},
               'verified_url': None, 'verified_location': None,
               'landing_attempts': [], 'download_requested': download}
        row['status'] = ('unavailable' if discovery.get('status') == 'unavailable' else
                         'located' if row['locations'] else 'alternatives' if row['alternatives'] else
                         'embargoed' if row['embargoed'] else 'not_found')
        eligible = [location for location in row['locations']
                    if location.get('availability') == 'open' and not location.get('requires_selection')]
        urls = [location['pdf_url'] for location in eligible
                if location.get('downloadable') and location.get('pdf_url')]
        if download:
            landings = list(dict.fromkeys(location.get('landing_page_url') or location.get('url')
                                          for location in eligible if not location.get('pdf_url')))
            for url in [url for url in landings if url][:3]:
                source_location = next(location for location in eligible
                                       if (location.get('landing_page_url') or location.get('url')) == url)
                outcome = landing_resolver(url, record) if landing_resolver else _landing(source_location)
                row['landing_attempts'].append({'url': url, 'result': outcome})
                urls.extend(outcome.get('pdf_urls') or [])
        urls = list(dict.fromkeys(urls))[:5]
        row['eligible_pdf_urls'] = urls
        if download and urls:
            download_started = time.monotonic()
            result = (downloader or _download)(record, urls, directory)
            row['download_seconds'] = round(time.monotonic() - download_started, 3)
            row['attempts'] = result.attempts or {}
            row['verification'] = result.verification
            row['status'] = result.status or 'not_found'
            if row['status'] == 'not_found' and any(str(v).startswith('mismatch') for v in row['attempts'].values()):
                row['status'] = 'mismatch'
            if result.filepath and Path(result.filepath).is_file():
                row['filepath'] = str(result.filepath)
                row['pdf_bytes'] = Path(result.filepath).stat().st_size
            # The benchmark refuses success without both a file and actual
            # identity verification, even if a downloader mistakenly says success.
            if row['status'] == 'verified' and (not row['filepath'] or
                    (row['verification'] or {}).get('status') != 'verified'):
                row['status'] = 'unverifiable'
            if row['status'] == 'verified':
                row['verified_url'] = next((url for url, state in row['attempts'].items() if state == 'verified'), None)
                observed = row['locations'] + [attempt['result'].get('location') for attempt in row['landing_attempts']
                                               if attempt['result'].get('location')]
                row['verified_location'] = next((location for location in observed
                                                  if location.get('pdf_url') == row['verified_url']), None)
            row['download_error'] = result.error
        row['elapsed_seconds'] = round(time.monotonic() - start, 3)
        rows.append(row)
    counts = Counter(row['status'] for row in rows)
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'download_requested': download,
            'scope': 'Recent curated full-text smoke test; not a representative success-rate estimate.',
            'summary': {'cases': len(rows), 'verified': counts['verified'],
                        'pdf_bytes': sum(row['pdf_bytes'] for row in rows),
                        'provider_errors': sum(len(row['provider_errors']) for row in rows),
                        'statuses': dict(counts)}, 'cases': rows}


def _temporary_directory(value):
    path = Path(value).expanduser().resolve()
    roots = [Path(tempfile.gettempdir()).resolve(), Path('/tmp').resolve()]
    if not any(path != root and path.is_relative_to(root) for root in roots):
        raise argparse.ArgumentTypeError('Use a subdirectory inside the system temporary directory or /tmp')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Query full-text metadata APIs')
    parser.add_argument('--download', action='store_true', help='Also download eligible PDFs and verify identity')
    parser.add_argument('--download-dir', type=_temporary_directory)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--case', action='append', default=[], dest='case_ids')
    parser.add_argument('--providers', default='europepmc', help='Comma-separated europepmc,unpaywall,openalex')
    parser.add_argument('--email', help='Optional Unpaywall contact email')
    parser.add_argument('--timeout', type=float, default=8)
    parser.add_argument('--deadline', type=float, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.download and (not args.live or args.download_dir is None):
        parser.error('--download requires --live and --download-dir')
    cases = load_cases(args.cases)
    if args.case_ids:
        unknown = set(args.case_ids) - {case['id'] for case in cases}
        if unknown:
            parser.error('Unknown case IDs: ' + ', '.join(sorted(unknown)))
        cases = [case for case in cases if case['id'] in args.case_ids]
    if not args.live:
        report = {'live': False, 'message': 'No network requests made. Use --live for location metadata; --download explicitly enables PDFs.',
                  'cases': cases}
    else:
        sys.path.insert(0, str(ROOT))
        from src.acquisition.recent_open_access import RecentOpenAccessDiscovery
        providers = tuple(value.strip() for value in args.providers.split(',') if value.strip())
        if not providers or any(value not in RecentOpenAccessDiscovery.PROVIDERS for value in providers):
            parser.error('Unknown or empty provider list')
        service = RecentOpenAccessDiscovery(providers=providers, email=args.email,
                                             timeout=args.timeout, deadline=args.deadline)
        report = run_cases(cases, service, download=args.download, download_dir=args.download_dir)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
