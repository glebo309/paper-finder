"""Deterministic local concurrency tests; no download sources are contacted."""
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.config import Config
from src.core.pipeline import AcquisitionPipeline
import src.core.pipeline as pipeline_module


def pipeline(monkeypatch, parallel=True, timeout=2):
    config = Config()
    config.pipeline.parallel_execution = parallel
    config.pipeline.method_timeout = timeout
    config.network.max_workers = 2
    obj = AcquisitionPipeline(config=config, metadata_resolver=Mock())
    monkeypatch.setattr(pipeline_module, "verify_document_identity", lambda *a: {"status": "verified", "reasons": []}, raising=False)
    # Old validator stub permits the historical implementation to reach its race.
    monkeypatch.setattr(pipeline_module, "validate_pdf_matches_metadata", lambda *a, **kw: True, raising=False)
    return obj


def write(path, marker):
    path.write_bytes(b"%PDF-1.4\n" + marker.encode() * 2048)
    return True


def test_losing_worker_cannot_overwrite_winning_file(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    loser_started, release_loser, loser_finished = threading.Event(), threading.Event(), threading.Event()
    paths = []
    def winner(doi, path, metadata):
        paths.append(path)
        assert loser_started.wait(1)
        return write(path, "winner")
    def loser(doi, path, metadata):
        paths.append(path)
        loser_started.set()
        try:
            assert release_loser.wait(2)
            return write(path, "loser")
        finally:
            loser_finished.set()
    obj.register_source("winner", winner, "fast")
    obj.register_source("loser", loser, "fast")
    output = tmp_path / "paper.pdf"
    try:
        result = obj.execute("10.1000/example", output, {})
        assert result.success and result.source == "winner"
    finally:
        release_loser.set()
    assert loser_finished.wait(1)
    # Wait for executor result handling as well as source return without relying
    # on sleep: registering another callback runs after the worker's cleanup.
    threading.Event().wait(.05)
    assert b"winner" in output.read_bytes()
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("parallel", [True, False])
def test_verification_exception_fails_closed_and_cleans_up(monkeypatch, tmp_path, parallel):
    obj = pipeline(monkeypatch, parallel)
    paths = []
    def source(doi, path, metadata):
        paths.append(path)
        return write(path, "unverified")
    def crash(*args, **kwargs):
        raise ValueError("cannot extract text")
    monkeypatch.setattr(pipeline_module, "verify_document_identity", crash, raising=False)
    monkeypatch.setattr(pipeline_module, "validate_pdf_matches_metadata", crash)
    obj.register_source("source", source)
    output = tmp_path / "out.pdf"
    result = obj.execute("10.1000/example", output, {})
    assert result.success is False
    assert not output.exists()
    assert all(not path.exists() for path in paths)
    assert "unverifiable" in result.attempts["source"]


def test_browser_opening_does_not_beat_later_verified_download(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    opened = threading.Event()
    def browser(*args):
        obj._browser_opened = True
        opened.set()
        return True
    def source(doi, path, metadata):
        assert opened.wait(1)
        return write(path, "verified")
    obj.register_source("Open Access (Browser)", browser, "fast")
    obj.register_source("PDF source", source, "medium")
    result = obj.execute("10.1000/example", tmp_path / "out.pdf", {})
    assert result.success is True
    assert result.filepath is not None
    assert result.source == "PDF source"


def test_browser_opening_alone_is_not_download_success(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    def browser(*args):
        obj._browser_opened = True
        return True
    obj.register_source("Open Access (Browser)", browser)
    result = obj.execute("10.1000/example", tmp_path / "out.pdf", {})
    assert result.success is False
    assert "browser" in result.attempts["Open Access (Browser)"].lower()


def test_timeout_prevents_late_output_and_cleans_temp(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch, timeout=.03)
    release, done = threading.Event(), threading.Event()
    paths = []
    def slow(doi, path, metadata):
        paths.append(path)
        release.wait(2)
        try:
            return write(path, "too late")
        finally:
            done.set()
    obj.register_source("slow", slow)
    output = tmp_path / "out.pdf"
    try:
        result = obj.execute("10.1000/example", output, {})
        assert not result.success
    finally:
        release.set()
    assert done.wait(1)
    threading.Event().wait(.05)
    assert not output.exists()
    assert all(not path.exists() for path in paths)


def test_existing_output_never_overwritten(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    source = Mock(side_effect=lambda doi, path, metadata: write(path, "new"))
    obj.register_source("new", source)
    output = tmp_path / "out.pdf"
    output.write_bytes(b"keep original")
    result = obj.execute("10.1000/example", output, {})
    assert not result.success
    assert output.read_bytes() == b"keep original"
    source.assert_not_called()


def test_failed_attempts_are_aggregated_across_tiers(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    obj.register_source("first", lambda *args: False, "fast")
    obj.register_source("second", lambda *args: False, "medium")
    result = obj.execute("10.1000/example", tmp_path / "out.pdf", {})
    assert not result.success
    assert set(result.attempts) == {"first", "second"}


def test_pre_requested_cancellation_is_not_reset_by_execute(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    source = Mock(side_effect=lambda doi, path, metadata: write(path, "new"))
    obj.register_source("new", source)
    obj.request_cancel()
    result = obj.execute("10.1000/example", tmp_path / "out.pdf", {})
    assert not result.success
    assert "cancel" in result.error.lower()
    source.assert_not_called()


def test_explicit_source_exclusion_is_per_operation(tmp_path):
    from src.core.pipeline import AcquisitionPipeline
    from src.core.config import Config
    pipeline = AcquisitionPipeline(config=Config())
    calls = []
    pipeline.register_source('excluded', lambda *args: calls.append('excluded'), tier='fast')
    pipeline.register_source('retained', lambda *args: calls.append('retained'), tier='fast')
    pipeline.execute('10.1234/test', tmp_path / 'one.pdf', {}, exclude_sources=('excluded',))
    assert calls == ['retained']
    assert all(source.enabled for source in pipeline.sources)


def test_all_tiers_start_together_even_when_old_worker_limit_is_one(monkeypatch, tmp_path):
    obj = pipeline(monkeypatch)
    obj.config.network.max_workers = 1
    barrier = threading.Barrier(3)
    called = []
    def source(name, winner=False):
        def run(doi, path, metadata):
            called.append(name)
            barrier.wait(timeout=1)
            return write(path, name) if winner else False
        return run
    obj.register_source('fast', source('fast'), 'fast')
    obj.register_source('medium', source('medium'), 'medium')
    obj.register_source('slow', source('slow', True), 'slow')
    result = obj.execute('10.1234/paper', tmp_path/'race.pdf', {})
    assert result.success and result.source == 'slow'
    assert set(called) == {'fast','medium','slow'}


def test_operation_sources_join_race_without_mutating_registration(monkeypatch, tmp_path):
    from src.core.pipeline import SourceMethod
    obj = pipeline(monkeypatch)
    started = threading.Event()
    def registered(doi,path,metadata):
        started.set()
        return False
    def extra(doi,path,metadata):
        assert started.wait(1)
        return write(path,'direct')
    obj.register_source('registered',registered,'slow')
    result = obj.execute('10.1234/paper',tmp_path/'extra.pdf',{},additional_sources=(SourceMethod('direct',extra,'medium'),))
    assert result.success and result.source == 'direct'
    assert obj.get_registered_sources() == ['registered']


def test_rejected_candidate_does_not_stop_other_tiers(monkeypatch,tmp_path):
    obj = pipeline(monkeypatch)
    rejected = threading.Event()
    def verify(path,record):
        if b'wrong' in path.read_bytes():
            rejected.set()
            return {'status':'mismatch','reasons':['Different DOI']}
        return {'status':'verified','reasons':[]}
    monkeypatch.setattr(pipeline_module,'verify_document_identity',verify)
    obj.register_source('wrong',lambda doi,path,metadata:write(path,'wrong'),'fast')
    def correct(doi,path,metadata):
        assert rejected.wait(1)
        return write(path,'correct')
    obj.register_source('correct',correct,'slow')
    result = obj.execute('10.1234/paper',tmp_path/'correct.pdf',{})
    assert result.success and result.source == 'correct'
    assert 'mismatch' in result.attempts['wrong']


def test_old_worker_cancel_event_stays_set_after_reset_and_new_operation(monkeypatch,tmp_path):
    from src.core.pipeline import SourceMethod
    obj = pipeline(monkeypatch)
    started,release,finished = threading.Event(),threading.Event(),threading.Event()
    observed = []
    def old(doi,path,metadata):
        event = pipeline_module.current_operation_stop_event()
        assert event is not None
        started.set()
        release.wait(2)
        observed.extend([event.is_set(), pipeline_module.operation_cancelled(),obj._check_cancel()])
        finished.set()
        return write(path,'old')
    obj.register_source('old',old)
    results = []
    thread = threading.Thread(target=lambda:results.append(obj.execute('10.1234/old',tmp_path/'old.pdf',{})))
    thread.start()
    try:
        assert started.wait(1)
        obj.request_cancel()
        obj._reset_cancel()
        new = obj.execute('10.1234/new',tmp_path/'new.pdf',{},exclude_sources=('old',),
            additional_sources=(SourceMethod('new',lambda doi,path,meta:write(path,'new'),'fast'),))
        assert new.success
    finally:
        release.set()
        thread.join(2)
    assert finished.wait(1)
    assert observed == [True,True,True]
    assert results and not results[0].success
    assert not (tmp_path/'old.pdf').exists()


def test_source_specific_verification_policy_is_per_operation(monkeypatch,tmp_path):
    obj = pipeline(monkeypatch)
    seen = []
    metadata = {'title':'A paper','verification_policy':{'original':True}}
    def verify(path,record):
        seen.append(record['verification_policy'])
        return {'status':'verified','reasons':[]}
    monkeypatch.setattr(pipeline_module,'verify_document_identity',verify)
    obj.register_source('legacy',lambda doi,path,meta:write(path,'legacy'))
    result = obj.execute('10.1234/paper',tmp_path/'policy.pdf',metadata,
                         verification_policies={'legacy':{'require_identifier':True}})
    assert result.success
    assert seen == [{'original':True,'require_identifier':True}]
    assert metadata['verification_policy'] == {'original':True}


def test_sequential_opt_out_does_not_launch_after_verified_winner(monkeypatch,tmp_path):
    obj = pipeline(monkeypatch,parallel=False)
    calls = []
    obj.register_source('first',lambda doi,path,meta:calls.append('first') or False,'fast')
    obj.register_source('winner',lambda doi,path,meta:calls.append('winner') or write(path,'winner'),'medium')
    obj.register_source('unused',lambda doi,path,meta:calls.append('unused') or False,'slow')
    result = obj.execute('10.1234/paper',tmp_path/'sequential.pdf',{})
    assert result.success
    assert calls == ['first','winner']


def test_cancelled_adapter_does_not_abort_other_worker_or_leak_candidate(monkeypatch, tmp_path):
    from src.core.cancellation import AcquisitionCancelled
    obj = pipeline(monkeypatch)
    cancelled = threading.Event()
    paths = []
    def abandoned(doi, path, metadata):
        paths.append(path)
        write(path, 'abandoned')
        cancelled.set()
        raise AcquisitionCancelled('Adapter stopped')
    def winner(doi, path, metadata):
        assert cancelled.wait(1)
        return write(path, 'winner')
    obj.register_source('abandoned', abandoned)
    obj.register_source('winner', winner)
    result = obj.execute('10.1234/paper', tmp_path/'winner.pdf', {})
    assert result.success and result.source == 'winner'
    assert result.attempts['abandoned'] == 'cancelled'
    assert all(not path.exists() for path in paths)
    assert not list(tmp_path.glob('.paperfinder-*'))
