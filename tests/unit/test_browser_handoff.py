from types import SimpleNamespace
from unittest.mock import Mock

from test_local_import import record
from test_document_identity import TARGET, pdf
from src.acquisition.browser_handoff import BrowserDownloadWatcher


def matching_pdf(folder):
    return pdf(folder, TARGET['title'] + '\nJohn Jumper\nAbstract\nResults')


def test_watches_new_stable_matching_pdf_and_preserves_original(tmp_path):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    output = tmp_path / 'library'
    watcher = BrowserDownloadWatcher(record(), downloads, output)
    source = matching_pdf(downloads)
    original = source.read_bytes()
    assert watcher.poll() is None
    result = watcher.poll()
    assert result.success and result.status == 'verified'
    assert result.filepath.parent == output
    assert source.read_bytes() == original
    assert watcher.finished and watcher.status == 'verified'
    assert watcher.poll() is result


def test_preexisting_files_are_ignored_but_modified_files_are_candidates(tmp_path):
    source = matching_pdf(tmp_path)
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path / 'out')
    assert watcher.poll() is None and watcher.poll() is None
    source.write_bytes(source.read_bytes() + b'\n')
    assert watcher.poll() is None
    assert watcher.poll().success


def test_changing_file_needs_two_observations_of_same_fingerprint(tmp_path, monkeypatch):
    importer = Mock(return_value=SimpleNamespace(success=True, status='verified'))
    monkeypatch.setattr('src.acquisition.browser_handoff.import_local_pdf', importer)
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path / 'out')
    source = tmp_path / 'paper.pdf'
    source.write_bytes(b'%PDF-a')
    assert watcher.poll() is None
    source.write_bytes(b'%PDF-longer')
    assert watcher.poll() is None
    assert not importer.called
    assert watcher.poll().success


def test_partial_symlink_and_oversized_files_are_not_imported(tmp_path, monkeypatch):
    importer = Mock(side_effect=AssertionError('Unsafe candidate'))
    monkeypatch.setattr('src.acquisition.browser_handoff.import_local_pdf', importer)
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out', max_size_mb=.0001)
    (tmp_path/'paper.pdf.crdownload').write_bytes(b'%PDF-')
    (tmp_path/'paper.download.pdf').write_bytes(b'%PDF-')
    target = tmp_path/'target.bin'
    target.write_bytes(b'%PDF-')
    (tmp_path/'link.pdf').symlink_to(target)
    (tmp_path/'large.pdf').write_bytes(b'%PDF-' + b'x'*1024)
    assert watcher.poll() is None and watcher.poll() is None
    assert not importer.called


def test_wrong_pdf_is_ignored_then_matching_download_can_win(tmp_path):
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out')
    wrong = pdf(tmp_path, 'A completely different scientific article\nJane Smith\nAbstract\nResults')
    assert watcher.poll() is None
    assert watcher.poll() is None
    assert 'match' in watcher.message.lower() or 'ignored' in watcher.message.lower()
    assert wrong.exists()
    wrong.rename(tmp_path/'wrong.pdf')
    matching_pdf(tmp_path)
    assert watcher.poll() is None
    result = watcher.poll()
    assert result.success
    assert (tmp_path/'wrong.pdf').exists()


def test_cancel_and_timeout_are_terminal_and_do_not_import(tmp_path):
    clock = [0]
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out', timeout=10, clock=lambda:clock[0])
    clock[0] = 10
    assert watcher.poll().status == 'timeout'
    assert watcher.finished
    other = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out')
    other.cancel()
    assert other.poll().status == 'cancelled'
    assert other.finished


def test_missing_download_directory_is_an_actionable_error(tmp_path):
    watcher = BrowserDownloadWatcher(record(), tmp_path/'missing', tmp_path/'out')
    result = watcher.poll()
    assert result.status == 'error' and not result.success
    assert 'folder' in watcher.message.lower() or 'directory' in watcher.message.lower()


def test_only_bounded_candidates_are_verified_per_poll(tmp_path, monkeypatch):
    importer = Mock(return_value=SimpleNamespace(success=False, status='mismatch', error='Wrong document'))
    monkeypatch.setattr('src.acquisition.browser_handoff.import_local_pdf', importer)
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out')
    for index in range(100):
        (tmp_path/f'{index}.pdf').write_bytes(b'%PDF-')
    watcher.poll()
    watcher.poll()
    assert 0 < importer.call_count <= 20


def test_institution_configuration_loads_and_serializes(tmp_path):
    from src.core.config import Config
    settings = tmp_path/'settings.yaml'
    settings.write_text('institutional:\n  label: University Library\n  login_url: https://library.example.org/login\n  proxy_template: "https://proxy.example.org/login?url={url}"\n')
    config = Config.from_file(settings)
    assert config.institutional.label == 'University Library'
    assert config.to_dict()['institutional']['proxy_template'].endswith('{url}')


def test_cancel_during_import_never_accepts_success_or_deletes_existing_output(tmp_path, monkeypatch):
    existing = tmp_path/'existing.pdf'
    existing.write_bytes(b'user-owned')
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out')
    (tmp_path/'new.pdf').write_bytes(b'%PDF-new')
    def importing(*args, **kwargs):
        watcher.cancel()
        return SimpleNamespace(success=True, status='verified', filepath=existing)
    monkeypatch.setattr('src.acquisition.browser_handoff.import_local_pdf', importing)
    assert watcher.poll() is None
    result = watcher.poll()
    assert not result.success and result.status == 'cancelled'
    assert existing.read_bytes() == b'user-owned'


def test_deadline_during_import_is_terminal_timeout(tmp_path, monkeypatch):
    clock = [0.0]
    watcher = BrowserDownloadWatcher(record(), tmp_path, tmp_path/'out', timeout=5, clock=lambda:clock[0])
    (tmp_path/'new.pdf').write_bytes(b'%PDF-new')
    def importing(*args, **kwargs):
        clock[0] = 6
        assert kwargs['cancel_check']()
        return SimpleNamespace(success=True, status='verified')
    monkeypatch.setattr('src.acquisition.browser_handoff.import_local_pdf', importing)
    assert watcher.poll() is None
    result = watcher.poll()
    assert not result.success and result.status == 'timeout'
