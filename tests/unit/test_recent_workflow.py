from unittest.mock import Mock
from types import SimpleNamespace
from paper_finder import PaperFinder, DownloadResult
from test_document_identity import TARGET, pdf


def finder():
    f = PaperFinder.__new__(PaperFinder)
    f.session = Mock()
    f.config = SimpleNamespace(validation=SimpleNamespace(max_size_mb=1))
    f.pipeline = None
    f._cancel_requested = False
    f._browser_opened = False
    f._browser_callback = None
    return f


def record():
    return dict(TARGET, identifier={'type': 'doi', 'value': TARGET['doi']})


def test_recent_copy_is_tried_before_legacy_sources_and_retains_version(tmp_path):
    f = finder()
    path = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')
    location = {'pdf_url': 'https://repository.example/accepted.pdf', 'url': 'https://repository.example/accepted.pdf', 'downloadable': True, 'version': 'acceptedVersion', 'source': 'unpaywall', 'license': 'cc-by'}
    f.find_access_options = Mock(return_value={'locations': [location], 'alternatives': [], 'errors': {}, 'status': 'found'})
    def download(rec, urls, directory):
        assert urls == [location['pdf_url']]
        assert rec['fulltext_locations'] == [location]
        return DownloadResult(True, filepath=path, attempts={urls[0]: 'verified'})
    f._download_record_urls = Mock(side_effect=download)
    f._execute_pipeline = Mock(side_effect=AssertionError('Should not contact legacy sources'))
    result = f.find_record(record(), tmp_path, recent_sources=True)
    assert result.success
    assert result.metadata['fulltext_location']['version'] == 'acceptedVersion'
    assert result.metadata['access_options']['status'] == 'found'


def test_preprint_alternative_is_exposed_without_automatic_download(tmp_path):
    f = finder()
    alternative = {'url': 'https://preprint.example/manuscript', 'pdf_url': 'https://preprint.example/manuscript.pdf', 'version': 'submittedVersion', 'requires_selection': True}
    f.find_access_options = Mock(return_value={'locations': [], 'alternatives': [alternative], 'errors': {}, 'status': 'alternatives'})
    f._download_record_urls = Mock(side_effect=AssertionError('Preprints must be explicitly selected'))
    f._execute_pipeline = Mock(return_value=DownloadResult(False, error='No verified document'))
    result = f.find_record(record(), tmp_path, recent_sources=True)
    assert not result.success
    assert result.metadata['access_options']['alternatives'] == [alternative]


def test_recent_lookup_failure_does_not_hide_legacy_result(tmp_path):
    f = finder()
    f.find_access_options = Mock(side_effect=RuntimeError('provider failed'))
    f._execute_pipeline = Mock(return_value=DownloadResult(False, error='No verified document'))
    result = f.find_record(record(), tmp_path, recent_sources=True)
    assert not result.success
    f._execute_pipeline.assert_called_once()
    assert result.metadata['access_options']['errors']


def test_recent_route_does_not_repeat_unversioned_legacy_oa_sources(tmp_path):
    f = finder()
    f.find_access_options = Mock(return_value={'locations': [], 'alternatives': [], 'errors': {}})
    f._execute_pipeline = Mock(return_value=DownloadResult(False))
    f.find_record(record(), tmp_path, recent_sources=True)
    excluded = f._execute_pipeline.call_args.kwargs.get('exclude_sources', ())
    assert {'Unpaywall', 'Europe PMC', 'Preprints Enhanced', 'Open Access (Browser)'} <= set(excluded)


def test_known_open_landing_page_resolves_advertised_pdf(monkeypatch, tmp_path):
    f = finder()
    location = {'url': 'https://repository.example/article', 'landing_page_url': 'https://repository.example/article', 'downloadable': False, 'availability': 'open', 'version': 'acceptedVersion'}
    expanded = dict(location, pdf_url='https://repository.example/article.pdf', downloadable=True)
    lookup = Mock(return_value=expanded)
    monkeypatch.setattr('src.acquisition.recent_open_access.discover_landing_pdf', lookup)
    f.find_access_options = Mock(return_value={'locations': [location], 'errors': {}})
    path = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')
    f._download_record_urls = Mock(return_value=DownloadResult(True, filepath=path, attempts={expanded['pdf_url']: 'verified'}))
    f._execute_pipeline = Mock(side_effect=AssertionError('No legacy request needed'))
    result = f.find_record(record(), tmp_path, recent_sources=True)
    assert result.success
    lookup.assert_called_once()
    assert result.metadata['fulltext_location']['version'] == 'acceptedVersion'
    assert f._download_record_urls.call_args.args[1] == [expanded['pdf_url']]


def test_find_forwards_recent_source_settings(tmp_path):
    f = finder()
    f.identity_resolver = Mock()
    f.identity_resolver.resolve.return_value = record()
    f.find_record = Mock(return_value=DownloadResult(False))
    f.find('a paper', tmp_path, recent_sources=True, contact_email='reader@university.edu')
    assert f.find_record.call_args.kwargs['recent_sources'] is True
    assert f.find_record.call_args.kwargs['contact_email'] == 'reader@university.edu'


def test_recent_lookup_precedes_flattened_pdf_and_blocks_known_preprint(monkeypatch, tmp_path):
    f = finder()
    rec = record()
    rec['pdf_urls'] = ['https://repo.example/preprint.pdf']
    alternative = {'pdf_url': rec['pdf_urls'][0], 'version': 'submittedVersion', 'requires_selection': True}
    f.find_access_options = Mock(return_value={'locations': [], 'alternatives': [alternative], 'errors': {}})
    f._download_record_urls = Mock(side_effect=AssertionError('Must not silently download known preprint'))
    f._execute_pipeline = Mock(side_effect=AssertionError('Legacy version-blind fallback could reintroduce this preprint'))
    result = f.find_record(rec, tmp_path, recent_sources=True)
    assert not result.success
    assert result.metadata['access_options']['alternatives'] == [alternative]


def test_cancel_during_copy_lookup_keeps_cancelled_status(tmp_path):
    f = finder()
    def cancelled(*args, **kwargs):
        f._cancel_requested = True
        return {'locations': [], 'errors': {}}
    f.find_access_options = cancelled
    f._execute_pipeline = Mock(side_effect=AssertionError('Cancelled'))
    assert f.find_record(record(), tmp_path, recent_sources=True).status == 'cancelled'


def test_landing_failure_is_reported_and_fallback_can_continue(monkeypatch, tmp_path):
    f = finder()
    f.find_access_options = Mock(return_value={'locations': [{'availability': 'open', 'url': 'https://repo.example/paper'}], 'errors': {}})
    monkeypatch.setattr('src.acquisition.recent_open_access.discover_landing_pdf', Mock(side_effect=RuntimeError('invalid response')))
    f._execute_pipeline = Mock(return_value=DownloadResult(False))
    result = f.find_record(record(), tmp_path, recent_sources=True)
    assert not result.success
    assert result.metadata['access_options']['errors']['landing_0']['kind'] == 'error'
    f._execute_pipeline.assert_called_once()


def test_known_indexed_preprint_remains_manual_when_current_lookup_fails(tmp_path):
    f = finder()
    rec = record()
    rec['indexed_locations'] = [{'pdf_url': 'https://repo.example/preprint.pdf', 'version': 'submittedVersion', 'requires_selection': True, 'source': 'openalex', 'is_oa': True}]
    f.find_access_options = Mock(side_effect=RuntimeError('Provider unavailable'))
    f._execute_pipeline = Mock(side_effect=AssertionError('Do not lose known manuscript-version evidence'))
    result = f.find_record(rec, tmp_path, recent_sources=True)
    assert not result.success
    assert result.metadata['access_options']['alternatives'][0]['version'] == 'submittedVersion'
