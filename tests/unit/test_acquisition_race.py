"""Exercise the normal selected-paper entry point with real PDF verification."""
import threading
from unittest.mock import Mock

from paper_finder import PaperFinder
from src.core.config import Config
from src.core.pipeline import AcquisitionPipeline
from test_document_identity import TARGET, pdf


def finder():
    obj = PaperFinder.__new__(PaperFinder)
    obj.config = Config()
    obj.config.pipeline.method_timeout = 3
    obj.pipeline = AcquisitionPipeline(config=obj.config, metadata_resolver=Mock())
    obj.session = Mock()
    obj._cancel_requested = False
    obj._browser_opened = False
    return obj


def record():
    return dict(TARGET, identifier={'type': 'doi', 'value': TARGET['doi']})


def response(data):
    obj = Mock(status_code=200, headers={})
    obj.iter_content.return_value = [data]
    return obj


def test_selected_paper_starts_all_discovery_and_legacy_routes_together(monkeypatch, tmp_path):
    obj = finder()
    fixture = tmp_path / 'fixtures'
    fixture.mkdir()
    correct = pdf(fixture, TARGET['title'] + '\nJohn Jumper\n' + TARGET['doi'] + '\nAbstract').read_bytes()
    # A barrier fails if any tier, metadata lookup, or provider waits for another.
    barrier = threading.Barrier(7)
    seen = set()
    lock = threading.Lock()
    def discovery(provider):
        with lock:
            seen.add(provider)
        barrier.wait(1.5)
        if provider == 'hal':
            return {'locations': [{'pdf_url': 'https://hal.science/article.pdf',
                'url': 'https://hal.science/article.pdf', 'downloadable': True,
                'version': 'acceptedVersion', 'source': 'hal'}]}
        return {'locations': [], 'errors': {}}
    monkeypatch.setattr('src.acquisition.recent_open_access.RecentOpenAccessDiscovery.discover',
        lambda self, doi: discovery(self.providers[0]))
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover',
        lambda self, rec: discovery(self.providers[0]))
    def legacy(*args):
        discovery('legacy')
        return False
    obj.pipeline.register_source('Deep source', legacy, 'slow')
    obj.session.get.return_value = response(correct)
    result = obj.find_record(record(), tmp_path / 'output', recent_sources=True)
    assert result.success, (result.error, result.attempts)
    assert seen == {'legacy', 'hal', 'zenodo', 'europepmc', 'openalex', 'unpaywall', 'publisher'}
    assert result.source == 'HAL repository'
    assert result.metadata['fulltext_location']['version'] == 'acceptedVersion'
    assert len(list((tmp_path / 'output').glob('*.pdf'))) == 1


def test_wrong_candidate_does_not_block_later_url_from_same_route(monkeypatch, tmp_path):
    obj = finder()
    wrong = pdf(tmp_path, 'Completely unrelated study\nJane Smith\nAbstract').read_bytes()
    correct = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\n' + TARGET['doi'] + '\nAbstract').read_bytes()
    rec = record()
    rec['pdf_urls'] = ['https://example.org/wrong.pdf', 'https://example.org/right.pdf']
    obj.session.get.side_effect = [response(wrong), response(correct)]
    result = obj.find_record(rec, tmp_path / 'output')
    assert result.success
    assert result.source == 'Indexed PDF links'
    assert result.metadata['candidate_attempts']['Indexed PDF links'][rec['pdf_urls'][0]] == 'mismatch'
    assert result.filepath.read_bytes() == correct


def test_discovered_preprint_is_not_downloaded_but_other_route_can_win(monkeypatch, tmp_path):
    obj = finder()
    rec = record()
    rec['indexed_locations'] = [{'pdf_url': 'https://example.org/preprint.pdf',
        'version': 'submittedVersion', 'requires_selection': True}]
    rec['pdf_urls'] = ['https://example.org/preprint.pdf']
    content = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\n' + TARGET['doi'] + '\nAbstract').read_bytes()
    monkeypatch.setattr('src.acquisition.recent_open_access.RecentOpenAccessDiscovery.discover', lambda *a: {})
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover', lambda *a: {})
    def legacy(doi, path, metadata):
        path.write_bytes(content)
        return True
    obj.pipeline.register_source('Independent repository', legacy)
    result = obj.find_record(rec, tmp_path / 'output', recent_sources=True)
    assert result.success
    obj.session.get.assert_not_called()
    assert result.metadata['access_options']['alternatives'][0]['version'] == 'submittedVersion'


def test_unclassified_title_only_copy_cannot_win_recent_race(monkeypatch, tmp_path):
    obj = finder()
    content = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract').read_bytes()
    monkeypatch.setattr('src.acquisition.recent_open_access.RecentOpenAccessDiscovery.discover', lambda *a: {})
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover', lambda *a: {})
    def legacy(doi, path, metadata):
        path.write_bytes(content)
        return True
    obj.pipeline.register_source('Unclassified repository', legacy)
    result = obj.find_record(record(), tmp_path / 'output', recent_sources=True)
    assert not result.success
    assert 'unverifiable' in result.attempts['Unclassified repository']


def test_completed_provider_preprint_evidence_blocks_conflicting_provider(monkeypatch, tmp_path):
    from src.acquisition.racing import DiscoveryRace
    obj = finder()
    race = DiscoveryRace(obj, record(), recent_sources=True)
    url = 'https://example.org/manuscript.pdf'
    race.reports['OpenAlex discovery'] = {'alternatives': [
        {'pdf_url': url, 'version': 'submittedVersion', 'requires_selection': True}]}
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover',
        lambda *a: {'locations': [{'pdf_url': url, 'downloadable': True, 'version': 'publishedVersion'}]})
    route = next(source for source in race.sources if source.name == 'HAL repository')
    assert not route.function(TARGET['doi'], tmp_path / 'candidate.pdf', record())
    obj.session.get.assert_not_called()


def test_preprint_evidence_arriving_during_download_rejects_candidate(monkeypatch, tmp_path):
    from src.acquisition.racing import DiscoveryRace
    obj = finder()
    race = DiscoveryRace(obj, record(), recent_sources=True)
    url = 'https://example.org/manuscript.pdf'
    content = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\n' + TARGET['doi'] + '\nAbstract').read_bytes()
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover',
        lambda *a: {'locations': [{'pdf_url': url, 'downloadable': True, 'version': 'publishedVersion'}]})
    def get(*args, **kwargs):
        race.reports['OpenAlex discovery'] = {'alternatives': [
            {'pdf_url': url, 'version': 'submittedVersion', 'requires_selection': True}]}
        return response(content)
    obj.session.get.side_effect = get
    route = next(source for source in race.sources if source.name == 'HAL repository')
    assert not route.function(TARGET['doi'], tmp_path / 'candidate.pdf', record())
    assert not (tmp_path / 'candidate.pdf').exists()


def test_confirmed_open_copy_can_override_stale_closed_access(monkeypatch, tmp_path):
    from src.acquisition.racing import DiscoveryRace
    obj = finder()
    race = DiscoveryRace(obj, record(), recent_sources=True)
    url = 'https://example.org/paper.pdf'
    race.reports['OpenAlex discovery'] = {'closed': [{'url': url, 'availability': 'closed'}]}
    content = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\n' + TARGET['doi'] + '\nAbstract').read_bytes()
    monkeypatch.setattr('src.acquisition.repository_discovery.RepositoryDiscovery.discover',
        lambda *a: {'locations': [{'pdf_url': url, 'url': url, 'availability': 'open',
            'downloadable': True, 'version': 'publishedVersion'}]})
    obj.session.get.return_value = response(content)
    route = next(source for source in race.sources if source.name == 'HAL repository')
    assert route.function(TARGET['doi'], tmp_path / 'candidate.pdf', record())
    assert (tmp_path / 'candidate.pdf').read_bytes() == content
