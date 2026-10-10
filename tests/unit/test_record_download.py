from unittest.mock import Mock
from pathlib import Path
import pytest
from paper_finder import PaperFinder, DownloadResult
from src.core.config import Config
from test_document_identity import pdf, TARGET


@pytest.fixture
def finder():
    config = Config()
    config.cache.enabled = False
    instance = PaperFinder(config=config, silent_init=True)
    instance.session = Mock()
    return instance


def record():
    return dict(TARGET, identifier={'type': 'doi', 'value': TARGET['doi']})


def response(body=b'', status=200):
    result = Mock(status_code=status, headers={})
    result.iter_content.return_value = [body]
    return result


def test_tries_next_url_after_wrong_pdf_and_verifies_real_document(finder, tmp_path):
    wrong = pdf(tmp_path, 'A different paper\nJane Smith\nAbstract\nSomething else').read_bytes()
    correct = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults').read_bytes()
    finder.session.get.side_effect = [response(wrong), response(correct)]
    result = finder._download_record_urls(record(), ['https://example.org/wrong.pdf', 'https://example.org/right.pdf'], tmp_path)
    assert result.success and result.status == 'verified'
    assert result.filepath.read_bytes() == correct
    assert result.attempts['https://example.org/wrong.pdf'] == 'mismatch'
    assert not list(tmp_path.glob('.paperfinder-*'))


def test_no_doi_candidate_acquires_provider_pdf(finder, tmp_path):
    body = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults').read_bytes()
    finder.session.get.return_value = response(body)
    candidate = dict(TARGET, doi=None, identifier={'type': 'openalex', 'value': 'https://openalex.org/W1'}, pdf_urls=['https://example.org/main.pdf'])
    result = finder.find_record(candidate, tmp_path)
    assert result.success and result.metadata['identifier']['type'] == 'openalex'


def test_locations_are_bounded(finder, tmp_path):
    finder.session.get.return_value = response(status=404)
    urls = [f'https://example.org/{i}.pdf' for i in range(20)]
    finder._download_record_urls(record(), urls, tmp_path)
    assert finder.session.get.call_count <= 5


def test_cancelled_download_stays_cancelled(finder, tmp_path):
    res = response()
    def chunks(**kwargs):
        finder._cancel_requested = True
        yield b'%PDF-1.4'
    res.iter_content.side_effect = chunks
    finder.session.get.return_value = res
    result = finder._download_record_urls(record(), ['https://example.org/file.pdf'], tmp_path)
    assert result.status == 'cancelled' and not result.success
    assert not list(tmp_path.glob('.paperfinder-*'))


def test_no_doi_landing_page_is_available_to_user(finder, tmp_path):
    candidate = dict(TARGET, doi=None, identifier={'type': 'openalex', 'value': 'W1'}, url='https://example.org/article')
    result = finder.find_record(candidate, tmp_path)
    assert result.status == 'located' and not result.success
    assert 'https://example.org/article' in result.metadata['links']


def test_verified_result_has_no_stale_error(finder, tmp_path):
    path = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')
    result = finder._verify_result(DownloadResult(False, filepath=path, error='Earlier source failed'), record())
    assert result.success and not result.error


def test_new_operation_resets_previous_pipeline_cancel(finder, tmp_path):
    finder.pipeline.request_cancel()
    finder.pipeline.execute = Mock(return_value=DownloadResult(False))
    finder.find_record(record(), tmp_path)
    assert not finder.pipeline._cancel_requested


def test_cancel_after_final_chunk_prevents_publication(finder, tmp_path):
    body = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults').read_bytes()
    def chunks(**kwargs):
        yield body
        finder.request_cancel()
    res = response()
    res.iter_content.side_effect = chunks
    finder.session.get.return_value = res
    result = finder._download_record_urls(record(), ['https://example.org/main.pdf'], tmp_path)
    assert result.status == 'cancelled' and not result.success
    assert not list(tmp_path.glob('10.1038*.pdf'))


def test_concurrent_destination_creation_is_never_overwritten(finder, tmp_path, monkeypatch):
    body = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults').read_bytes()
    finder.session.get.return_value = response(body)
    allocate = finder._available_output
    created = []
    def race(directory, identifier):
        path = allocate(directory, identifier)
        if not created:
            path.write_bytes(b'other download')
            created.append(path)
        return path
    monkeypatch.setattr(finder, '_available_output', race)
    result = finder._download_record_urls(record(), ['https://example.org/main.pdf'], tmp_path)
    assert created[0].read_bytes() == b'other download'
    assert result.success and result.filepath != created[0]


def test_doi_fallback_preserves_direct_mismatch_evidence(finder, tmp_path):
    finder._download_record_urls = Mock(return_value=DownloadResult(
        False, attempts={'https://example.org/wrong.pdf': 'mismatch'}, status='not_found'))
    finder._execute_pipeline = Mock(return_value=DownloadResult(
        False, attempts={'repository': 'No PDF'}, status='not_found'))
    candidate = dict(record(), pdf_urls=['https://example.org/wrong.pdf'])
    result = finder.find_record(candidate, tmp_path)
    assert result.status == 'mismatch'
    assert result.attempts == {'https://example.org/wrong.pdf': 'mismatch', 'repository': 'No PDF'}


def test_verified_fallback_removes_only_own_unverified_download(finder, tmp_path):
    retained = tmp_path / 'own.unverified.pdf'
    retained.write_bytes(b'%PDF-unreadable')
    preexisting = tmp_path / 'previous.unverified.pdf'
    preexisting.write_bytes(b'keep this')
    verified = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')
    finder._download_record_urls = Mock(return_value=DownloadResult(
        False, filepath=retained, attempts={'direct': 'unverifiable'}, status='unverifiable'))
    finder._execute_pipeline = Mock(return_value=DownloadResult(
        True, filepath=verified, attempts={'repository': 'verified'}, status='verified'))
    result = finder.find_record(dict(record(), pdf_urls=['https://example.org/paper.pdf']), tmp_path)
    assert result.success
    assert not retained.exists()
    assert preexisting.read_bytes() == b'keep this'
    assert result.attempts == {'direct': 'unverifiable', 'repository': 'verified'}


def test_failed_fallback_keeps_unverified_file_and_all_attempts(finder, tmp_path):
    retained = tmp_path / 'own.unverified.pdf'
    retained.write_bytes(b'%PDF-unreadable')
    finder._download_record_urls = Mock(return_value=DownloadResult(
        False, filepath=retained, attempts={'direct': 'unverifiable'}, status='unverifiable'))
    finder._execute_pipeline = Mock(return_value=DownloadResult(
        False, attempts={'repository': 'No PDF'}, status='not_found'))
    result = finder.find_record(dict(record(), pdf_urls=['https://example.org/paper.pdf']), tmp_path)
    assert result.filepath == retained and retained.exists()
    assert result.attempts == {'direct': 'unverifiable', 'repository': 'No PDF'}
