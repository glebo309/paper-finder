"""UI state helpers do not load the downloader while browsing metadata."""
from unittest.mock import Mock


def test_changing_query_clears_previous_selection_and_download():
    from src.cli.search_helpers import begin_search
    state = {"search_result": {"query": "old"}, "selected_record": {"title": "old"}, "result": object(), "browser_url": "old", "search_log": "old"}
    begin_search(state, "new")
    assert state["query"] == "new"
    assert all(state[key] is None for key in ("search_result", "selected_record", "result", "browser_url"))


def test_select_candidate_uses_original_record_and_clears_download():
    from src.cli.search_helpers import select_candidate
    record = {"title": "A", "identifier": {"type": "openalex", "value": "W1"}}
    state = {"search_result": {"candidates": [record]}, "result": object(), "browser_url": "old"}
    select_candidate(state, 0)
    assert state["selected_record"] is record
    assert state["result"] is None
    assert state["browser_url"] is None


def test_direct_arxiv_uses_metadata_resolution_without_downloader(monkeypatch):
    from src.cli.search_helpers import search_reference
    record = {"title": "Attention Is All You Need", "identifier": {"type": "arxiv", "value": "1706.03762"}, "metadata_source": "arxiv"}
    resolve = Mock(return_value=record)
    monkeypatch.setattr("src.core.identity.IdentityResolver.resolve", resolve)
    result = search_reference("arXiv:1706.03762")
    assert result["status"] == "matched"
    assert result["selected"]["identifier"]["value"] == "1706.03762"
    resolve.assert_called_once_with("arXiv:1706.03762")


def test_streamlit_search_and_selection_are_metadata_only(monkeypatch):
    import pytest
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    import paper_finder
    first = {"title": "First paper", "identifier": {"type": "doi", "value": "10.1234/first"}, "doi": "10.1234/first", "sources": ["crossref"], "match_reasons": ["Exact title"], "score": 99.0}
    second = {"title": "Second paper", "identifier": {"type": "doi", "value": "10.1234/second"}, "doi": "10.1234/second", "sources": ["openalex"], "match_reasons": ["Related title"], "score": 80.0}
    payload = {"query": "test", "status": "ambiguous", "candidates": [first, second], "selected": None, "errors": {}}
    monkeypatch.setattr("src.cli.search_helpers.search_reference", Mock(return_value=payload))
    finder = Mock()
    finder.find_record.return_value = SimpleNamespace(success=False, filepath=None, source="fixture", status="located", error="", verification=None)
    factory = Mock(return_value=finder)
    monkeypatch.setattr(paper_finder, "PaperFinder", factory)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"))
    app.run()
    assert not app.exception
    factory.assert_not_called()
    app.text_input[0].input("test")
    next(button for button in app.button if button.label == "Find candidates").click().run()
    assert not app.exception
    assert len([button for button in app.button if button.label == "Select this paper"]) == 2
    factory.assert_not_called()
    app.button(key="select_1").click().run()
    assert app.session_state["selected_record"]["doi"] == "10.1234/second"
    factory.assert_not_called()
    next(button for button in app.button if button.label == "Download selected paper").click().run()
    assert not app.exception
    assert finder.find_record.call_args.args[0]["doi"] == "10.1234/second"
    assert any("No verified PDF" in element.value for element in app.info)
    app.text_input[0].input("new query")
    next(button for button in app.button if button.label == "Find candidates").click().run()
    assert app.session_state["selected_record"] is None
    assert app.session_state["result"] is None


def test_streamlit_unverified_file_remains_distinct_from_link(monkeypatch, tmp_path):
    import pytest
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    import paper_finder
    record = {"title": "Scanned paper", "identifier": {"type": "doi", "value": "10.1234/scan"}}
    path = tmp_path / "review.pdf"
    path.write_bytes(b"%PDF-unverified-fixture")
    result = SimpleNamespace(success=False, filepath=path, source="fixture", status="unverifiable", error="No extractable text", verification={"status": "unverifiable"})
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"))
    app.session_state["selected_record"] = record
    app.session_state["result"] = result
    app.session_state["browser_url"] = "https://example.org/paper.pdf"
    app.run()
    assert not app.exception
    assert any("could not be verified" in warning.value for warning in app.warning)
    assert any(str(path) in caption.value for caption in app.caption)
    assert not app.success


def test_streamlit_failed_retry_does_not_show_old_result(monkeypatch):
    import pytest
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    import paper_finder
    factory = Mock(side_effect=RuntimeError("Fixture failure"))
    monkeypatch.setattr(paper_finder, "PaperFinder", factory)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"))
    app.session_state["selected_record"] = {"title": "Selected", "identifier": {"type": "doi", "value": "10.1234/selected"}}
    app.session_state["result"] = SimpleNamespace(success=False, filepath=None, source="old", status="located", error="", verification=None)
    app.session_state["browser_url"] = "https://example.org/old.pdf"
    app.run()
    next(button for button in app.button if button.label == "Download selected paper").click().run()
    assert not app.exception
    assert app.session_state["result"] is None
    assert app.session_state["browser_url"] is None
    assert any("Fixture failure" in error.value for error in app.error)


def test_direct_identifier_preserves_provider_unavailability(monkeypatch):
    from src.cli.search_helpers import search_reference
    failure = {"identifier": {"type": "unknown", "value": None}, "title": None, "status": "unavailable", "error": "Metadata providers unavailable", "provider_errors": {"crossref": {"kind": "network_error"}}, "candidates": []}
    monkeypatch.setattr("src.core.identity.IdentityResolver.resolve", Mock(return_value=failure))
    outcome = search_reference("https://doi.org/10.1234/test")
    assert outcome["status"] == "unavailable"
    assert outcome["errors"]["crossref"]["kind"] == "network_error"


def test_book_date_normalized_for_snapshot_roundtrip(monkeypatch, tmp_path):
    from src.cli.search_helpers import search_reference, save_results, load_results
    record = {"title": "Book", "identifier": {"type": "isbn", "value": "9781464126116"}, "year": "January 1, 2013", "authors": ["Author"], "metadata_source": "isbn_db"}
    monkeypatch.setattr("src.core.identity.IdentityResolver.resolve", Mock(return_value=record))
    result = search_reference("9781464126116")
    assert result["selected"]["year"] == 2013
    snapshot = tmp_path / "book.json"
    save_results(snapshot, result)
    assert load_results(snapshot)["selected"]["publication_date"] == "January 1, 2013"


def test_streamlit_exposes_repository_identity_and_metadata_conflicts():
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    record = {
        'title': 'Original paper', 'identifier': {'type': 'doi', 'value': '10.1234/repost'},
        'doi': '10.1234/repost', 'arxiv_ids': ['1706.03762'],
        'metadata_warnings': ['Indexed DOI conflicts with repository metadata'],
        'record_urls': ['https://arxiv.org/abs/1706.03762'],
    }
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['search_result'] = {'query': 'original paper', 'status': 'ambiguous', 'candidates': [record]}
    app.run()
    assert not app.exception
    assert any('Indexed DOI conflicts' in item.value for item in app.warning)
    assert any('1706.03762' in item.value for item in app.caption)
    assert any(item.proto.url == 'https://arxiv.org/abs/1706.03762' for item in app.get('link_button'))


def test_recent_copies_visible_before_download_and_preprints_labelled(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    report = {'status': 'found', 'locations': [{'source': 'repository', 'version': 'acceptedVersion', 'license': 'cc-by', 'url': 'https://repo.example/paper.pdf', 'pdf_url': 'https://repo.example/paper.pdf'}], 'alternatives': [{'source': 'preprint server', 'version': 'submittedVersion', 'url': 'https://repo.example/preprint'}], 'embargoed': [], 'errors': {}}
    lookup = Mock(return_value=report)
    monkeypatch.setattr('src.acquisition.recent_open_access.RecentOpenAccessDiscovery.discover', lookup)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = {'title': 'A new paper', 'doi': '10.1234/new', 'identifier': {'type': 'doi', 'value': '10.1234/new'}}
    app.run()
    button = next((b for b in app.button if b.label == 'Find full-text copies'), None)
    assert button is not None
    button.click().run()
    assert not app.exception
    lookup.assert_called_once_with('10.1234/new')
    assert app.session_state['result'] is None
    rendered = ' '.join(x.value for x in app.markdown) + ' '.join(x.value for x in app.caption)
    assert 'Accepted manuscript' in rendered
    assert 'Preprint' in rendered
    assert any(x.proto.url == 'https://repo.example/paper.pdf' for x in app.get('link_button'))


def test_streamlit_shows_embargo_date_and_standalone_download_version(tmp_path):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['access_options'] = {'embargoed': [{'version': 'acceptedVersion', 'available_from': '2027-01-01'}]}
    app.run()
    assert not app.exception
    assert any('2027-01-01' in c.value for c in app.caption)
    path = tmp_path / 'verified.pdf'
    path.write_bytes(b'%PDF-test')
    app.session_state['access_options'] = None
    app.session_state['result'] = SimpleNamespace(success=True, filepath=path, source='repository', status='verified', error=None, verification=None, metadata={'fulltext_location': {'version': 'acceptedVersion'}})
    app.run()
    assert not app.exception
    assert any('Downloaded copy: Accepted manuscript' in c.value for c in app.caption)


def test_browser_download_import_is_reachable_and_uses_selected_identity(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    import streamlit
    selected = {'title': 'Recent paper', 'doi': '10.1234/recent', 'identifier': {'type': 'doi', 'value': '10.1234/recent'}}
    upload = SimpleNamespace(size=10, getbuffer=lambda: b'%PDF-local')
    monkeypatch.setattr(streamlit, 'file_uploader', Mock(return_value=upload))
    importer = Mock(return_value=SimpleNamespace(success=False, filepath=None, source='Browser/local PDF', status='mismatch', error='Wrong article', metadata=selected, verification={}))
    monkeypatch.setattr('src.acquisition.local_import.import_local_pdf', importer)
    monkeypatch.setattr('paper_finder.PaperFinder', Mock(side_effect=AssertionError('No downloader should start')))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = selected
    app.run()
    button = next((b for b in app.button if b.label == 'Verify and save browser PDF'), None)
    assert button is not None
    button.click().run()
    assert not app.exception
    assert importer.call_args.args[0]['doi'] == selected['doi']
    assert any('does not match' in e.value for e in app.error)
    assert any(e.proto.url == 'https://doi.org/10.1234/recent' for e in app.get('link_button'))


def test_search_change_cancels_active_browser_watch():
    from src.cli.search_helpers import begin_search
    watcher = Mock()
    state = {'browser_watch': watcher}
    begin_search(state, 'different paper')
    watcher.cancel.assert_called_once()
    assert state['browser_watch'] is None


def test_candidate_change_cancels_active_browser_watch():
    from src.cli.search_helpers import select_candidate
    watcher = Mock()
    state = {'browser_watch': watcher, 'search_result': {'candidates': [{'title': 'New'}]}}
    select_candidate(state, 0)
    watcher.cancel.assert_called_once()
    assert state['browser_watch'] is None


def test_browser_watch_controls_start_poll_and_cancel(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    selected = {'title': 'Recent paper', 'doi': '10.1234/recent', 'identifier': {'type': 'doi', 'value': '10.1234/recent'}}
    watcher = Mock(finished=False, status='waiting', message='Waiting for a new PDF.')
    watcher.poll.return_value = None
    factory = Mock(return_value=watcher)
    # Inject the contract so this UI test is independent of filesystem polling.
    import sys
    monkeypatch.setitem(sys.modules, 'src.acquisition.browser_handoff', SimpleNamespace(BrowserDownloadWatcher=factory))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = selected
    app.run()
    start = next((b for b in app.button if b.label == 'Watch for browser PDF'), None)
    assert start is not None
    app.text_input(key='browser_download_dir').input(str(tmp_path))
    start.click().run()
    assert not app.exception
    assert factory.call_args.args[0]['doi'] == selected['doi']
    assert Path(factory.call_args.args[1]) == tmp_path
    watcher.poll.assert_called()
    next(b for b in app.button if b.label == 'Stop watching').click().run()
    watcher.cancel.assert_called_once()
    assert app.session_state['browser_watch'] is None


def test_browser_watch_success_displays_verified_result(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    selected = {'title': 'Recent paper', 'doi': '10.1234/recent', 'identifier': {'type': 'doi', 'value': '10.1234/recent'}}
    pdf = tmp_path / 'verified.pdf'
    pdf.write_bytes(b'%PDF-test')
    result = SimpleNamespace(success=True, filepath=pdf, source='Browser/local PDF', status='verified', error=None, verification={'status': 'verified'}, metadata=selected)
    watcher = Mock(finished=True, status='verified', message='Verified and saved.')
    watcher.poll.return_value = result
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = selected
    app.session_state['browser_watch'] = watcher
    app.run()
    assert not app.exception
    assert app.session_state['result'] is result
    assert app.session_state['browser_watch'] is None
    assert any('verified' in item.value for item in app.success)


def test_institution_settings_build_proxy_and_login_links(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    monkeypatch.delenv('PAPER_FINDER_LIBRARY_PROXY', raising=False)
    monkeypatch.delenv('PAPER_FINDER_LIBRARY_LOGIN', raising=False)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = {'title': 'Test', 'doi': '10.1234/test', 'identifier': {'type': 'doi', 'value': '10.1234/test'}}
    app.run()
    proxy = next((t for t in app.text_input if t.label == 'Library proxy template (optional)'), None)
    assert proxy is not None
    proxy.input('https://library.example/login?url={url}').run()
    app.text_input(key='library_login').input('https://library.example/access').run()
    assert not app.exception
    urls = [b.proto.url for b in app.get('link_button')]
    assert 'https://library.example/login?url=https%3A%2F%2Fdoi.org%2F10.1234%2Ftest' in urls
    assert 'https://library.example/access' in urls
    app.text_input(key='library_proxy').input('javascript:alert(1)').run()
    assert not app.exception
    assert any('proxy' in e.value.lower() for e in app.sidebar.error)
    assert all(not b.proto.url.startswith('javascript:') for b in app.get('link_button'))


def test_web_institution_defaults_honor_config_and_invalid_proxy_has_no_handoff(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from types import SimpleNamespace
    monkeypatch.delenv('PAPER_FINDER_LIBRARY_PROXY', raising=False)
    monkeypatch.delenv('PAPER_FINDER_LIBRARY_LOGIN', raising=False)
    monkeypatch.setattr('src.core.config.get_config', lambda: SimpleNamespace(institutional={'proxy_template': 'https://library.example/proxy?url={url}', 'login_url': 'https://library.example/login'}))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'streamlit_app.py'))
    app.session_state['selected_record'] = {'title': 'Test', 'doi': '10.1234/test', 'identifier': {'type': 'doi', 'value': '10.1234/test'}}
    app.run()
    assert app.text_input(key='library_proxy').value == 'https://library.example/proxy?url={url}'
    assert app.text_input(key='library_login').value == 'https://library.example/login'
    app.text_input(key='library_proxy').input('broken').run()
    assert not app.exception
    assert not any(b.proto.label == 'Open publisher in browser' for b in app.get('link_button'))
    assert any('proxy' in e.value.lower() for e in app.sidebar.error)
