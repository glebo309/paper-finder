import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests


def test_cancelled_session_never_enters_transport(monkeypatch):
    from src.core.cancellation import CancellableSession, AcquisitionCancelled
    stop = threading.Event(); stop.set()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop)
    transport = Mock()
    monkeypatch.setattr(requests.Session, 'send', transport)
    with pytest.raises(AcquisitionCancelled):
        CancellableSession().get('https://example.org')
    transport.assert_not_called()
    assert not issubclass(AcquisitionCancelled, Exception)


def test_cancel_after_response_closes_it(monkeypatch):
    from src.core.cancellation import CancellableSession, AcquisitionCancelled
    stop = threading.Event()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop)
    response = Mock()
    def send(*args, **kwargs):
        stop.set()
        return response
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(AcquisitionCancelled):
        CancellableSession().send(requests.Request('GET', 'https://example.org').prepare())
    response.close.assert_called_once()


def test_cancellation_sleep_uses_operation_event(monkeypatch):
    from src.core.cancellation import cancellable_sleep, AcquisitionCancelled
    stop = Mock(); stop.is_set.return_value = False; stop.wait.return_value = True
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop)
    with pytest.raises(AcquisitionCancelled):
        cancellable_sleep(99)
    stop.wait.assert_called_once_with(99)


def test_session_captures_parent_event_for_nested_worker(monkeypatch):
    from src.core.cancellation import CancellableSession, AcquisitionCancelled
    stop = threading.Event()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop if threading.current_thread() is threading.main_thread() else None)
    session = CancellableSession()
    stop.set()
    transport = Mock()
    monkeypatch.setattr(requests.Session, 'send', transport)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(session.get, 'https://example.org')
        with pytest.raises(AcquisitionCancelled): future.result()
    transport.assert_not_called()


def test_bind_cancellation_propagates_event_to_nested_helper(monkeypatch):
    from src.core.cancellation import bind_cancellation, check_cancelled, AcquisitionCancelled
    stop = threading.Event()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop if threading.current_thread() is threading.main_thread() else None)
    callback = bind_cancellation(check_cancelled)
    stop.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(AcquisitionCancelled): pool.submit(callback).result()


def test_response_stream_stops_and_closes_between_chunks(monkeypatch):
    from src.core.cancellation import CancellableSession, AcquisitionCancelled
    stop = threading.Event()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop)
    response = Mock()
    response.iter_content.return_value = iter([b'first', b'second'])
    monkeypatch.setattr(requests.Session, 'request', lambda *args, **kwargs: response)
    received = CancellableSession().get('https://example.org', stream=True)
    chunks = received.iter_content(chunk_size=3)
    assert next(chunks) == b'first'
    stop.set()
    with pytest.raises(AcquisitionCancelled): next(chunks)
    response.close.assert_called_once()


def test_deep_crawl_retry_does_not_swallow_cancellation(monkeypatch):
    from src.core.cancellation import AcquisitionCancelled
    from src.acquisition.deep_crawler import search_with_retry
    stop = threading.Event(); stop.set()
    monkeypatch.setattr('src.core.pipeline.current_operation_stop_event', lambda: stop)
    with pytest.raises(AcquisitionCancelled):
        search_with_retry('https://example.org', max_retries=1)


def test_common_source_continues_after_wrong_first_pdf(monkeypatch, tmp_path):
    from src.core.base_source import SimpleAcquisitionSource
    class Source(SimpleAcquisitionSource):
        name = 'Test source'
        def get_download_urls(self, doi, metadata): return ['wrong', 'correct']
    source = Source(session=Mock())
    def download(url, path):
        path.write_bytes(b'%PDF-' + url.encode() + b'x' * 60000)
        return True
    source._download_from_url = Mock(side_effect=download)
    verify = Mock(side_effect=[{'status': 'mismatch'}, {'status': 'verified'}])
    monkeypatch.setattr('src.core.validation.verify_document_identity', verify)
    path = tmp_path / 'paper.pdf'
    result = source.try_acquire('10.1234/test', path, {'title': 'Exact main article title'})
    assert result.success
    assert source._download_from_url.call_count == 2
    assert path.read_bytes().startswith(b'%PDF-correct')
    assert verify.call_args.args[1]['doi'] == '10.1234/test'


def test_springer_helper_does_not_swallow_stop_signal():
    from src.core.cancellation import AcquisitionCancelled
    from src.acquisition.springer_enhanced import try_springer_sharedit
    session = Mock()
    session.get.side_effect = AcquisitionCancelled()
    with pytest.raises(AcquisitionCancelled):
        try_springer_sharedit('10.1007/example', session)
