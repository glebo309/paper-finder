"""Offline contract tests for identity selection and acquisition boundaries."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import paper_finder as module
from paper_finder import PaperFinder, DownloadResult
from src.core.identity import IdentityResolver


@pytest.fixture
def record():
    return {'identifier': {'type': 'doi', 'value': '10.1234/target'},
            'doi': '10.1234/target', 'title': 'A specific target paper',
            'authors': ['Alice Smith'], 'year': 2023, 'metadata_source': 'test'}


@pytest.fixture
def finder():
    f = PaperFinder.__new__(PaperFinder)
    f.session = Mock()
    f.config = SimpleNamespace(validation=SimpleNamespace(max_size_mb=1))
    f.pipeline = None
    f.identity_resolver = Mock()
    f._cancel_requested = False
    f._browser_opened = False
    f._browser_callback = None
    return f


def test_constructor_accepts_explicit_configuration_without_network(monkeypatch):
    from src.core.config import Config
    config = Config()
    config.cache.enabled = False
    monkeypatch.setattr(module.requests.Session, 'get', Mock(side_effect=AssertionError('constructor network')))
    monkeypatch.setattr(module, 'get_cache', Mock(side_effect=AssertionError('disabled cache used')))
    f = PaperFinder(config=config, silent_init=True)
    assert f.config is config
    assert f.cache is None


def test_ambiguous_identity_stops_before_acquisition(finder, record, tmp_path):
    finder.identity_resolver.resolve.return_value = {
        'identifier': {'type': 'title', 'value': 'target'},
        'status': 'ambiguous', 'candidates': [record], 'error': 'Choose a candidate'}
    finder.find_record = Mock(side_effect=AssertionError('must not acquire'))
    result = finder.find('target', tmp_path)
    assert not result.success
    assert result.status == 'ambiguous'
    assert result.metadata['candidates'] == [record]
    finder.session.get.assert_not_called()


def test_find_passes_verified_record_without_reresolving(finder, record, tmp_path):
    finder.identity_resolver.resolve.return_value = record
    finder.find_record = Mock(return_value=DownloadResult(success=False))
    finder.find('a citation', tmp_path)
    assert finder.find_record.call_args.args[0] == record


def test_selected_record_used_by_pipeline(finder, record, tmp_path, monkeypatch):
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=False, error='unavailable'))
    result = finder.find_record(record, tmp_path)
    assert not result.success
    assert finder._execute_pipeline.call_args.kwargs['metadata'] == record
    finder.identity_resolver.resolve.assert_not_called()


def test_browser_link_is_not_a_verified_download(finder, record, tmp_path):
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=True, source='Browser', metadata=record))
    result = finder.find_record(record, tmp_path)
    assert not result.success
    assert result.status == 'located'
    assert result.verification['status'] == 'unverifiable'


def test_wrong_document_cannot_be_reported_as_success(finder, record, tmp_path, monkeypatch):
    pdf = tmp_path / 'candidate.pdf'
    pdf.write_bytes(b'%PDF-1.4\nwrong')
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=True, filepath=pdf, metadata=record))
    monkeypatch.setattr('src.core.validation.verify_document_identity', lambda *a: {'status': 'mismatch', 'reasons': ['Different title']}, raising=False)
    result = finder.find_record(record, tmp_path)
    assert not result.success
    assert result.status == 'mismatch'
    assert result.verification['reasons'] == ['Different title']


def test_unreadable_document_stays_explicitly_unverified(finder, record, tmp_path, monkeypatch):
    pdf = tmp_path / 'scan.pdf'
    pdf.write_bytes(b'%PDF-1.4\nscan')
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=True, filepath=pdf))
    monkeypatch.setattr('src.core.validation.verify_document_identity', lambda *a: {'status': 'unverifiable', 'reasons': ['No text']}, raising=False)
    result = finder.find_record(record, tmp_path)
    assert not result.success
    assert result.status == 'unverifiable'
    assert result.filepath == pdf


def test_verified_pdf_keeps_canonical_selected_metadata(finder, record, tmp_path, monkeypatch):
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4\narticle')
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=True, filepath=pdf, metadata={'title': 'unexpected replacement'}))
    monkeypatch.setattr('src.core.validation.verify_document_identity', lambda *a: {'status': 'verified', 'reasons': ['Title and DOI']}, raising=False)
    result = finder.find_record(record, tmp_path)
    assert result.success and result.status == 'verified'
    assert result.metadata['title'] == record['title']


def test_existing_output_is_not_overwritten(finder, record, tmp_path):
    existing = tmp_path / '10.1234_target.pdf'
    existing.write_bytes(b'user document')
    finder._execute_pipeline = Mock(return_value=DownloadResult(success=False))
    finder.find_record(record, tmp_path)
    output = finder._execute_pipeline.call_args.args[1]
    assert output != existing
    assert existing.read_bytes() == b'user document'


def test_cancellation_reaches_pipeline(finder):
    finder.pipeline = Mock()
    finder.request_cancel()
    finder.pipeline.request_cancel.assert_called_once()


def test_unknown_explicit_doi_never_substitutes_another_work(monkeypatch):
    session = Mock()
    session.headers = {}
    response = Mock(status_code=404, url='https://doi.org/10.1234/missing')
    session.get.return_value = response
    resolver = IdentityResolver(session=session)
    resolver._resolve_citation = Mock(side_effect=AssertionError('DOI must not become text search'))
    result = resolver.resolve('Missing reference 2024 DOI: 10.1234/missing')
    assert result['identifier']['value'] != '10.1234/something-else'
    resolver._resolve_citation.assert_not_called()
