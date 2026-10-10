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
