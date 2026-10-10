from pathlib import Path
from test_document_identity import TARGET, pdf


def record():
    return dict(TARGET, identifier={'type': 'doi', 'value': TARGET['doi']})


def test_import_verifies_browser_download_without_changing_original(tmp_path):
    from src.acquisition.local_import import import_local_pdf
    source = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')
    original = source.read_bytes()
    output = tmp_path / 'library'
    result = import_local_pdf(record(), source, output)
    assert result.success and result.status == 'verified'
    assert result.filepath.parent == output
    assert result.filepath.read_bytes() == original == source.read_bytes()
    assert result.metadata['imported_copy']['version'] == 'unknown'
    second = import_local_pdf(record(), source, output)
    assert second.filepath != result.filepath
    assert result.filepath.read_bytes() == original
    assert not list(output.glob('.paperfinder-*'))


def test_wrong_pdf_is_not_added_to_library(tmp_path):
    from src.acquisition.local_import import import_local_pdf
    source = pdf(tmp_path, 'A completely different scientific publication\nJane Smith\nAbstract\nResults')
    result = import_local_pdf(record(), source, tmp_path / 'library')
    assert not result.success
    assert result.status == 'mismatch'
    assert result.filepath is None
    assert source.is_file()
    assert not list((tmp_path / 'library').glob('*.pdf'))


def test_import_rejects_oversized_file_before_verification(monkeypatch, tmp_path):
    from src.acquisition.local_import import import_local_pdf
    source = tmp_path / 'large.pdf'
    source.write_bytes(b'%PDF-' + b'x' * 1024)
    def forbidden(*a, **k):
        raise AssertionError('Size must be checked first')
    monkeypatch.setattr('src.core.validation.verify_document_identity', forbidden)
    result = import_local_pdf(record(), source, tmp_path / 'library', max_size_mb=.0001)
    assert not result.success and result.status == 'error'
    assert 'size' in result.error.lower()


def test_import_clears_previous_download_version_claim(tmp_path):
    from src.acquisition.local_import import import_local_pdf
    rec = record()
    rec['fulltext_location'] = {'version': 'publishedVersion'}
    source = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract')
    result = import_local_pdf(rec, source, tmp_path / 'library')
    assert result.success
    assert 'fulltext_location' not in result.metadata
    assert rec['fulltext_location']['version'] == 'publishedVersion'


def test_cancellation_during_verification_prevents_publication(tmp_path, monkeypatch):
    from src.acquisition.local_import import import_local_pdf
    cancelled = [False]
    source = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract')
    output = tmp_path/'library'
    output.mkdir()
    existing = output/'existing.pdf'
    existing.write_bytes(b'user document')
    def verify(*args):
        cancelled[0] = True
        return {'status':'verified', 'reasons':['Matching DOI']}
    monkeypatch.setattr('src.core.validation.verify_document_identity', verify)
    result = import_local_pdf(record(), source, output, cancel_check=lambda:cancelled[0])
    assert not result.success and result.status == 'cancelled'
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b'user document'
    assert source.exists()


def test_cancel_guard_is_checked_immediately_before_atomic_publish(tmp_path, monkeypatch):
    from src.acquisition.local_import import import_local_pdf
    source = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract')
    state = {'verified':False, 'checks':0}
    def verify(*args):
        state['verified'] = True
        return {'status':'verified', 'reasons':['Matching DOI']}
    def cancel_check():
        if state['verified']:
            state['checks'] += 1
        return state['checks'] >= 2
    monkeypatch.setattr('src.core.validation.verify_document_identity', verify)
    result = import_local_pdf(record(), source, tmp_path/'library', cancel_check=cancel_check)
    assert result.status == 'cancelled'
    assert not list((tmp_path/'library').glob('*.pdf'))
    assert not list((tmp_path/'library').glob('.paperfinder-*'))
