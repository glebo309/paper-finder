"""Recent full-text evidence never confuses a location with a verified download."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[2] / 'tools' / 'benchmark_recent_fulltext.py'


def harness():
    spec = importlib.util.spec_from_file_location('recent_benchmark', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case():
    return {'id': 'recent-paper', 'cohort': 'hard', 'record': {
        'identifier': {'type': 'doi', 'value': '10.1234/recent'}, 'doi': '10.1234/recent',
        'title': 'Recent enzyme chemistry paper', 'authors': ['A Researcher'],
        'publication_date': '2026-09-23', 'year': 2026}}


def location(url='https://repository.org/paper.pdf', **extra):
    return {'url': url, 'pdf_url': url, 'downloadable': True, 'availability': 'open',
            'requires_selection': False, 'version': 'acceptedVersion', 'license': 'cc-by',
            'source': 'europepmc', **extra}


class Service:
    def __init__(self, locations=None, **extra):
        self.result = {'doi': '10.1234/recent', 'status': 'found', 'locations': locations or [],
                       'alternatives': [], 'embargoed': [], 'closed': [], 'errors': {}, **extra}
        self.calls = []
    def discover(self, doi):
        self.calls.append(doi)
        return self.result


def test_metadata_only_never_invokes_downloader_or_claims_success():
    service = Service([location()])
    def forbidden(*args):
        raise AssertionError('Downloading was not requested')
    result = harness().run_cases([case()], service, downloader=forbidden)
    assert result['summary']['verified'] == 0
    row = result['cases'][0]
    assert row['status'] == 'located' and row['pdf_bytes'] == 0
    assert row['publication_date'] == '2026-09-23'
    assert row['locations'][0]['version'] == 'acceptedVersion'
    assert row['locations'][0]['license'] == 'cc-by'


def test_only_available_non_alternative_urls_download_and_report_actual_bytes(tmp_path):
    service = Service([location()], alternatives=[location('https://repo.org/preprint.pdf')],
                      embargoed=[location('https://repo.org/future.pdf')], closed=[location('https://repo.org/closed.pdf')])
    calls = []
    def download(record, urls, directory):
        calls.append((record, urls))
        path = directory / 'verified.pdf'
        path.write_bytes(b'%PDF-verified-test')
        return SimpleNamespace(status='verified', success=True, filepath=path,
                               verification={'status': 'verified', 'reasons': ['Exact DOI']},
                               attempts={urls[0]: 'verified'}, error='')
    result = harness().run_cases([case()], service, download=True, download_dir=tmp_path, downloader=download)
    assert calls[0][1] == ['https://repository.org/paper.pdf']
    row = result['cases'][0]
    assert row['status'] == 'verified' and row['pdf_bytes'] == len(b'%PDF-verified-test')
    assert row['verification']['reasons'] == ['Exact DOI']
    assert result['summary']['verified'] == 1


def test_network_failure_not_reported_as_closed_or_absent():
    service = Service(status='unavailable', errors={'europepmc': {'kind': 'timeout'}})
    row = harness().run_cases([case()], service)['cases'][0]
    assert row['status'] == 'unavailable'
    assert row['provider_errors']['europepmc']['kind'] == 'timeout'
    assert row['closed'] == []


def test_mismatched_pdf_attempt_is_reported_as_mismatch(tmp_path):
    def download(record, urls, directory):
        return SimpleNamespace(status='not_found', success=False, filepath=None,
                               verification=None, attempts={urls[0]: 'mismatch'}, error='No verified PDF')
    row = harness().run_cases([case()], Service([location()]), download=True,
                              download_dir=tmp_path, downloader=download)['cases'][0]
    assert row['status'] == 'mismatch'
    assert row['pdf_bytes'] == 0


def test_landing_discovery_bounded_and_disabled_without_download(tmp_path):
    locations = [location(f'https://repo.org/item/{i}', pdf_url=None, downloadable=False,
                          landing_page_url=f'https://repo.org/item/{i}') for i in range(5)]
    calls = []
    def resolve(url, record):
        calls.append(url)
        return {'pdf_urls': [], 'status': 'not_found'}
    module = harness()
    module.run_cases([case()], Service(locations), landing_resolver=resolve)
    assert not calls
    module.run_cases([case()], Service(locations), download=True, download_dir=tmp_path,
                     landing_resolver=resolve, downloader=lambda *args: pytest.fail('No PDF URLs'))
    assert len(calls) == 3


def test_cli_default_dry_run_and_download_requires_explicit_live(capsys):
    module = harness()
    assert module.main([]) == 0
    assert 'live' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        module.main(['--download'])


def test_fixture_contains_two_recent_hard_cases_and_available_control():
    module = harness()
    cases = module.load_cases(module.DEFAULT_CASES)
    assert len(cases) == 3
    assert sum(c['cohort'] == 'hard' for c in cases) == 2
    assert all(c['record']['publication_date'].startswith('2026-09') for c in cases)


def test_success_without_file_and_identity_evidence_is_not_verified(tmp_path):
    def download(record, urls, directory):
        return SimpleNamespace(status='verified', success=True, filepath=None,
                               verification=None, attempts={}, error='')
    report = harness().run_cases([case()], Service([location()]), download=True,
                                 download_dir=tmp_path, downloader=download)
    assert report['summary']['verified'] == 0
    assert report['cases'][0]['status'] == 'unverifiable'


def test_cli_rejects_downloads_outside_temporary_directory():
    with pytest.raises(SystemExit):
        harness().main(['--live', '--download', '--download-dir', str(Path.home() / 'Downloads')])


def test_verified_copy_identifies_actual_source_version_and_license(tmp_path):
    def download(record, urls, directory):
        path = directory / 'verified.pdf'
        path.write_bytes(b'%PDF-placeholder')
        return SimpleNamespace(status='verified', success=True, filepath=path,
                               verification={'status': 'verified'}, attempts={urls[0]: 'verified'}, error='')
    row = harness().run_cases([case()], Service([location()]), download=True,
                              download_dir=tmp_path, downloader=download)['cases'][0]
    assert row['verified_url'] == 'https://repository.org/paper.pdf'
    assert row['verified_location']['version'] == 'acceptedVersion'
    assert row['verified_location']['license'] == 'cc-by'
