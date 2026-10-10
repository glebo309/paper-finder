"""Book acquisition uses staged files and checks each candidate before returning."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyPDF2 import PdfWriter
from paper_finder import PaperFinder

RECORD = {"identifier": {"type": "isbn", "value": "9781234567897"},
          "title": "A Specific Book", "authors": ["Alice Smith"]}


@pytest.fixture
def book_finder(monkeypatch):
    finder = PaperFinder.__new__(PaperFinder)
    finder.session = Mock()
    finder.config = SimpleNamespace(telegram=SimpleNamespace(underground_enabled=False))
    finder._cancel_requested = False
    monkeypatch.setattr("src.core.validation.verify_document_identity", lambda *a: {"status": "verified", "reasons": []})
    return finder


def write_pdf(path):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)
    return True


def adapters(monkeypatch, anna, libgen):
    monkeypatch.setattr("src.acquisition.annas_archive.try_fetch_from_annas_archive", anna)
    monkeypatch.setattr("src.acquisition.libgen.try_libgen_main", libgen)


def test_existing_book_is_not_overwritten(book_finder, monkeypatch, tmp_path):
    existing = tmp_path / "A Specific Book.pdf"
    existing.write_bytes(b"Keep this user document")
    seen=[]
    def source(**kwargs):
        seen.append(kwargs["output_file"])
        return write_pdf(kwargs["output_file"])
    adapters(monkeypatch, source, Mock(return_value=False))
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert result.success and result.filepath.exists()
    assert existing.read_bytes() == b"Keep this user document"
    assert seen[0].parent != tmp_path
    assert not seen[0].parent.exists()


def test_wrong_first_book_does_not_hide_verified_second(book_finder, monkeypatch, tmp_path):
    calls=[]
    def verify(path, record):
        calls.append(path)
        return {"status": "mismatch" if len(calls)==1 else "verified", "reasons": []}
    monkeypatch.setattr("src.core.validation.verify_document_identity", verify)
    second=Mock(side_effect=lambda title, authors, path: write_pdf(path))
    adapters(monkeypatch, lambda **kw: write_pdf(kw["output_file"]), second)
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert result.success and result.source == "LibGen Books"
    assert len(calls) == 2
    assert result.attempts["Anna's Archive (Book)"] == "mismatch"
    assert all(not path.exists() for path in calls)


def test_browser_only_source_continues_to_pdf(book_finder, monkeypatch, tmp_path):
    second=Mock(side_effect=lambda title, authors, path: write_pdf(path))
    adapters(monkeypatch, Mock(return_value=True), second)
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert result.success and result.filepath is not None
    second.assert_called_once()


def test_book_cancellation_after_source_prevents_publication(book_finder, monkeypatch, tmp_path):
    def source(**kw):
        write_pdf(kw["output_file"])
        book_finder._cancel_requested=True
        return True
    second=Mock()
    adapters(monkeypatch, source, second)
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert not result.success and result.status == "cancelled"
    assert list(tmp_path.iterdir()) == []
    second.assert_not_called()


def test_book_unverified_scan_remains_explicitly_labelled(book_finder, monkeypatch, tmp_path):
    monkeypatch.setattr("src.core.validation.verify_document_identity", lambda *a: {"status":"unverifiable", "reasons":["No text"]})
    adapters(monkeypatch, lambda **kw: write_pdf(kw["output_file"]), Mock(return_value=False))
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert not result.success and result.status == "unverifiable"
    assert result.filepath.exists() and "unverified" in result.filepath.name
    assert len(list(tmp_path.iterdir())) == 1


def test_source_exception_does_not_abort_fallback_or_leak_files(book_finder, monkeypatch, tmp_path):
    def source(**kw):
        write_pdf(kw["output_file"])
        raise OSError("interrupted write")
    adapters(monkeypatch, source, lambda title, authors, path: write_pdf(path))
    result=book_finder._handle_book(RECORD["identifier"]["value"], RECORD, tmp_path)
    assert result.success and result.source == "LibGen Books"
    assert len(list(tmp_path.iterdir())) == 1


def test_publication_collision_keeps_competing_file(book_finder, monkeypatch, tmp_path):
    import os
    real_link=os.link
    collision=[True]
    def link(source, destination):
        if collision[0]:
            collision[0]=False
            Path(destination).write_bytes(b'Concurrent user file')
        return real_link(source, destination)
    monkeypatch.setattr(os, 'link', link)
    adapters(monkeypatch, lambda **kw: write_pdf(kw['output_file']), Mock(return_value=False))
    result=book_finder._handle_book(RECORD['identifier']['value'], RECORD, tmp_path)
    assert result.success
    assert (tmp_path / 'A Specific Book.pdf').read_bytes() == b'Concurrent user file'
    assert result.filepath.name != 'A Specific Book.pdf'


def test_verified_fallback_removes_only_own_unverified_book(book_finder, monkeypatch, tmp_path):
    verification=Mock(side_effect=[{'status':'unverifiable', 'reasons':['No text']}, {'status':'verified','reasons':[]}])
    monkeypatch.setattr('src.core.validation.verify_document_identity', verification)
    existing=tmp_path/'A Specific Book.unverified.pdf'
    existing.write_bytes(b'User-owned scan')
    adapters(monkeypatch, lambda **kw: write_pdf(kw['output_file']), lambda title, authors, path: write_pdf(path))
    result=book_finder._handle_book(RECORD['identifier']['value'], RECORD, tmp_path)
    assert result.success
    assert existing.read_bytes() == b'User-owned scan'
    assert len(list(tmp_path.iterdir())) == 2


def test_verification_cancellation_does_not_publish_book(book_finder, monkeypatch, tmp_path):
    def verify(*args):
        book_finder._cancel_requested=True
        return {'status':'verified','reasons':[]}
    monkeypatch.setattr('src.core.validation.verify_document_identity', verify)
    adapters(monkeypatch, lambda **kw: write_pdf(kw['output_file']), Mock(return_value=False))
    result=book_finder._handle_book(RECORD['identifier']['value'], RECORD, tmp_path)
    assert not result.success and result.status == 'cancelled'
    assert list(tmp_path.iterdir()) == []
