"""The documented CLI is exercised through its actual module entry point."""
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECORD = {"title": "Highly accurate protein structure prediction with AlphaFold", "doi": "10.1038/s41586-021-03819-2", "identifier": {"type": "doi", "value": "10.1038/s41586-021-03819-2"}, "authors": ["John Jumper"], "year": 2021, "sources": ["crossref", "openalex"], "match_reasons": ["Title matches"], "score": .96}


def invoke(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    try:
        runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
    except SystemExit as exc:
        return exc.code
    return 0


@pytest.fixture
def services(monkeypatch):
    discovery = Mock()
    discovery.search.return_value = {"query": "alphafold", "status": "matched", "candidates": [RECORD], "selected": RECORD, "errors": {}}
    from src.core.discovery import _doi
    module = ModuleType("src.core.discovery")
    module._doi = _doi
    module.DiscoveryService = Mock(return_value=discovery)
    monkeypatch.setitem(sys.modules, "src.core.discovery", module)
    finder = Mock()
    finder.find_record.return_value = SimpleNamespace(success=True, filepath=Path("paper.pdf"), source="fixture", error="", metadata=RECORD, status="downloaded")
    finder_module = ModuleType("paper_finder")
    finder_module.PaperFinder = Mock(return_value=finder)
    monkeypatch.setitem(sys.modules, "paper_finder", finder_module)
    return discovery, finder_module.PaperFinder, finder


def test_search_json_never_constructs_acquisition(monkeypatch, services, capsys):
    discovery, constructor, _ = services
    assert invoke(monkeypatch, ["search", "alphafold", "--json", "--limit", "5", "--mode", "discover"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"][0]["doi"] == RECORD["doi"]
    discovery.search.assert_called_once_with("alphafold", limit=5, mode="discover")
    constructor.assert_not_called()


def test_ambiguous_acquire_stops_before_downloader(monkeypatch, services, capsys):
    discovery, constructor, _ = services
    discovery.search.return_value.update(status="ambiguous", selected=None)
    assert invoke(monkeypatch, ["acquire", "alphafold", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ambiguous"
    assert payload["candidates"] == [RECORD]
    constructor.assert_not_called()


def test_selected_acquire_uses_record_and_clean_json(monkeypatch, services, capsys, tmp_path):
    discovery, constructor, finder = services
    discovery.search.return_value.update(status="ambiguous", selected=None)
    def download(*args, **kwargs):
        print("backend progress")
        return SimpleNamespace(success=True, filepath=tmp_path / "paper.pdf", source="fixture", error="", metadata=RECORD, status="downloaded")
    finder.find_record.side_effect = download
    assert invoke(monkeypatch, ["acquire", "alphafold", "--select", "1", "--json", "--output", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["success"] is True
    assert "backend progress" in output.err
    assert finder.find_record.call_args.args[0] == RECORD
    constructor.assert_called_once()


def test_out_of_range_selection_does_not_download(monkeypatch, services, capsys):
    _, constructor, _ = services
    assert invoke(monkeypatch, ["acquire", "alphafold", "--select", "2", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_selection"
    constructor.assert_not_called()


def test_provider_failure_is_json_and_nonzero(monkeypatch, services, capsys):
    discovery, constructor, _ = services
    discovery.search.return_value.update(status="unavailable", selected=None, candidates=[], errors={"crossref": "offline"})
    assert invoke(monkeypatch, ["search", "alphafold", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    constructor.assert_not_called()


def test_actual_constructor_accepts_cli_configuration(monkeypatch, tmp_path, capsys):
    import paper_finder
    from src.core.config import Config
    discovery = ModuleType("src.core.discovery")
    discovery.DiscoveryService = Mock(return_value=SimpleNamespace(search=Mock(return_value={"query": RECORD["doi"], "status": "matched", "selected": RECORD, "candidates": [RECORD], "errors": {}})))
    monkeypatch.setitem(sys.modules, "src.core.discovery", discovery)
    config = Config()
    monkeypatch.setattr("src.core.config.load_config", lambda path: config)
    monkeypatch.setattr("src.utils.scihub_updater.load_scihub_domains", lambda **kwargs: [])
    monkeypatch.setattr(paper_finder, "get_cache", lambda: None)
    monkeypatch.setattr(paper_finder.PaperFinder, "_register_sources", lambda self: None)
    def fake_acquire(self, *args, **kwargs):
        assert self.config is config
        return paper_finder.DownloadResult(success=True, source="fixture", filepath=tmp_path / "paper.pdf")
    monkeypatch.setattr(paper_finder.PaperFinder, "find_record", fake_acquire, raising=False)
    monkeypatch.setattr(paper_finder.PaperFinder, "acquire", fake_acquire)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}")
    assert invoke(monkeypatch, ["acquire", RECORD["doi"], "--config", str(cfg)]) == 0


def test_located_link_is_not_reported_as_downloaded(monkeypatch, services, capsys):
    _, _, finder = services
    def locate(record, output_dir, browser_callback, **kwargs):
        browser_callback(record["doi"], "https://example.org/paper.pdf")
        return SimpleNamespace(success=False, filepath=None, source="publisher", error="No verified PDF saved", metadata=record, status="located", verification=None)
    finder.find_record.side_effect = locate
    assert invoke(monkeypatch, ["acquire", "alphafold", "--json"]) == 1
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["status"] == "located"
    assert outcome["url"] == "https://example.org/paper.pdf"
    assert not outcome["success"]


def test_snapshot_keeps_displayed_candidate_order_without_search(monkeypatch, services, capsys, tmp_path):
    discovery, _, finder = services
    other = {**RECORD, "title": "Another work", "doi": "10.1234/other", "identifier": {"type": "doi", "value": "10.1234/other"}}
    discovery.search.return_value.update(status="ambiguous", selected=None, candidates=[other, RECORD])
    snapshot = tmp_path / "candidates.json"
    assert invoke(monkeypatch, ["search", "alphafold", "--save-results", str(snapshot), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"][1] == RECORD
    saved = json.loads(snapshot.read_text())
    assert saved["version"] == 1
    discovery.search.reset_mock()
    discovery.search.side_effect = AssertionError("A saved selection must not requery")
    assert invoke(monkeypatch, ["acquire", "--from-results", str(snapshot), "--select", "2", "--json", "--output", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True
    discovery.search.assert_not_called()
    assert finder.find_record.call_args.args[0] == RECORD


@pytest.mark.parametrize("snapshot", [
    {"version": 2, "result": {"query": "x", "status": "matched", "candidates": [RECORD], "selected": RECORD}},
    {"version": 1, "result": {"query": "x", "status": "matched", "candidates": [{"title": "x", "identifier": {"type": "doi", "value": "not-a-doi"}}]}},
    {"version": 1, "result": {"query": "x", "status": "matched", "candidates": [RECORD], "selected": {**RECORD, "doi": "10.1234/injected"}}},
    {"version": 1, "result": {"query": "x", "status": "matched", "candidates": [{**RECORD, "doi": "10.1234/conflicting"}], "selected": None}},
])
def test_invalid_snapshot_never_downloads(monkeypatch, services, capsys, tmp_path, snapshot):
    discovery, factory, _ = services
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(snapshot))
    assert invoke(monkeypatch, ["acquire", "--from-results", str(path), "--select", "1", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    discovery.search.assert_not_called()
    factory.assert_not_called()


def test_snapshot_acquisition_rejects_conflicting_query(monkeypatch, services, capsys, tmp_path):
    discovery, factory, _ = services
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"version": 1, "result": discovery.search.return_value}))
    assert invoke(monkeypatch, ["acquire", "unrelated query", "--from-results", str(path), "--json"]) == 1
    assert "reference" in json.loads(capsys.readouterr().out)["error"].lower()
    discovery.search.assert_not_called()
    factory.assert_not_called()


def test_refresh_flag_reaches_discovery(monkeypatch, services, capsys):
    assert invoke(monkeypatch, ['search', 'alphafold', '--refresh', '--json']) == 0
    sys.modules['src.core.discovery'].DiscoveryService.assert_called_once_with(refresh=True)


def test_acquire_recent_options_reach_finder(monkeypatch, services, tmp_path, capsys):
    _, _, finder = services
    assert invoke(monkeypatch, ['acquire', 'alphafold', '--refresh', '--skip-recent-sources',
        '--email', 'researcher@example.org', '--output', str(tmp_path), '--json']) == 0
    assert finder.find_record.call_args.kwargs['recent_sources'] is False
    assert finder.find_record.call_args.kwargs['contact_email'] == 'researcher@example.org'
    sys.modules['src.core.discovery'].DiscoveryService.assert_called_once_with(refresh=True)


def test_acquire_checks_recent_sources_by_default(monkeypatch, services, tmp_path, capsys):
    _, _, finder = services
    assert invoke(monkeypatch, ['acquire', 'alphafold', '--output', str(tmp_path), '--json']) == 0
    assert finder.find_record.call_args.kwargs['recent_sources'] is True


@pytest.fixture
def copies_service(monkeypatch):
    import src.acquisition.recent_open_access as recent
    service = Mock()
    service.discover.return_value = {'doi': RECORD['doi'], 'status': 'available',
        'locations': [{'url': 'https://example.org/paper.pdf', 'version': 'acceptedVersion',
                       'license': 'cc-by', 'source': 'unpaywall', 'downloadable': True}],
        'alternatives': [], 'embargoed': [], 'closed': [], 'errors': {}}
    factory = Mock(return_value=service)
    monkeypatch.setattr(recent, 'RecentOpenAccessDiscovery', factory)
    return factory, service


def test_copies_json_is_metadata_only(monkeypatch, services, copies_service, capsys):
    discovery, acquisition, _ = services
    factory, copies = copies_service
    assert invoke(monkeypatch, ['copies', RECORD['doi'], '--email', 'researcher@example.org', '--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['locations'][0]['version'] == 'acceptedVersion'
    factory.assert_called_once_with(email='researcher@example.org')
    copies.discover.assert_called_once_with(RECORD['doi'])
    discovery.search.assert_not_called()
    acquisition.assert_not_called()


def test_copies_text_explains_versions_embargo_and_no_download(monkeypatch, copies_service, capsys):
    _, copies = copies_service
    copies.discover.return_value['alternatives'] = [{'url': 'https://example.org/preprint', 'version': 'submittedVersion', 'source': 'openalex'}]
    copies.discover.return_value['embargoed'] = [{'url': 'https://example.org/embargo', 'version': 'acceptedVersion', 'available_from': '2027-01-01', 'source': 'unpaywall'}]
    assert invoke(monkeypatch, ['copies', RECORD['doi']]) == 0
    output = capsys.readouterr().out
    for expected in ('acceptedVersion', 'cc-by', 'unpaywall', 'submittedVersion', '2027-01-01', 'No files downloaded'):
        assert expected in output


def test_copies_no_locations_returns_nonzero(monkeypatch, copies_service, capsys):
    _, copies = copies_service
    copies.discover.return_value.update(locations=[], status='not_found')
    assert invoke(monkeypatch, ['copies', RECORD['doi'], '--json']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'not_found'


def test_copies_rejects_description_before_any_request(monkeypatch, copies_service, capsys):
    factory, _ = copies_service
    assert invoke(monkeypatch, ['copies', 'that protein folding paper', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'error'
    factory.assert_not_called()


def test_fresh_search_and_selection_clear_prior_access_options():
    from src.cli.search_helpers import begin_search, select_candidate
    state = {'access_options': {'locations': ['stale']}}
    begin_search(state, 'new query')
    assert state['access_options'] is None
    state.update(search_result={'candidates': [RECORD]}, access_options={'locations': ['stale']})
    select_candidate(state, 0)
    assert state['access_options'] is None
