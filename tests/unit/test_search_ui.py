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
