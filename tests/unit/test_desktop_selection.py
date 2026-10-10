"""Desktop result routing without creating a native Tk window."""
from unittest.mock import Mock
from paper_finder import DownloadResult
from gui import PaperFinderGUI


def gui():
    app = PaperFinderGUI.__new__(PaperFinderGUI)
    for name in ('search_button', 'stop_button', 'status_var', 'status_indicator', 'stop_spinner', 'log', 'result_visible'):
        setattr(app, name, Mock())
    app.result_visible.get.return_value = True
    app.result_fields = {key: Mock() for key in ('title', 'author', 'status', 'source', 'file')}
    app._show_candidates = Mock()
    return app


def test_ambiguous_result_exposes_candidate_chooser():
    app = gui()
    candidates = [{'title': 'One paper'}, {'title': 'Another paper'}]
    app._update_results(DownloadResult(False, status='ambiguous', metadata={'candidates': candidates}))
    app._show_candidates.assert_called_once_with(candidates)


def test_oa_flag_does_not_turn_failed_download_into_success():
    app = gui()
    app._update_results(DownloadResult(False, status='unverifiable', error='No text', metadata={'is_oa': True}))
    assert not any('✓' in str(call) for call in app.status_var.set.call_args_list)
    assert 'verif' in str(app.result_fields['status'].set.call_args).lower()


def test_return_key_cannot_start_another_search_while_busy():
    app = gui()
    app._search_active = True
    app.doi_var = Mock()
    app.search()
    app.doi_var.get.assert_not_called()


def test_unverifiable_without_file_is_not_labelled_saved():
    app = gui()
    app._update_results(DownloadResult(False, status='unverifiable', error='No text', metadata={}))
    assert 'saved' not in str(app.result_fields['status'].set.call_args).lower()


def test_recent_sources_toggle_is_visible_and_enabled_by_default(monkeypatch):
    import gui as module
    app = gui()
    app.search = Mock()
    app.browse_output = Mock()
    app.stop_search = Mock()
    variable = Mock(get=Mock(return_value=True))
    boolean = Mock(return_value=variable)
    monkeypatch.setattr(module.tk, 'BooleanVar', boolean)
    monkeypatch.setattr(module.tk, 'StringVar', Mock())
    for name in ('LabelFrame', 'Label', 'Entry', 'Button', 'Frame'):
        monkeypatch.setattr(module.ttk, name, Mock())
    checkbox = Mock()
    monkeypatch.setattr(module.ttk, 'Checkbutton', checkbox)
    app.build_input_section(Mock())
    boolean.assert_called_once_with(value=True)
    assert app.recent_sources is variable
    assert checkbox.call_args.kwargs['text'] == 'Prioritize recent full-text sources'
    assert checkbox.call_args.kwargs['variable'] is variable
    checkbox.return_value.grid.assert_called_once()


def test_worker_passes_recent_setting_for_reference_and_selected_record():
    for reference in ('10.1234/paper', {'title': 'Selected paper'}):
        for enabled in (True, False):
            app = gui()
            app.root = Mock()
            app.verbose_logging = Mock(get=Mock(return_value=False))
            app.finder = Mock()
            app._search_error = Mock()
            app._search_thread(reference, '/tmp/papers', recent_sources=enabled)
            method = app.finder.find_record if isinstance(reference, dict) else app.finder.find
            assert method.call_args.kwargs['recent_sources'] is enabled
            assert method.call_args.args == (reference, '/tmp/papers')


def test_search_captures_toggle_on_main_thread(monkeypatch):
    import gui as module
    app = gui()
    app.root = Mock()
    app.doi_var = Mock(get=Mock(return_value='10.1234/paper'))
    app.output_var = Mock(get=Mock(return_value='/tmp/papers'))
    app.recent_sources = Mock(get=Mock(return_value=False))
    for name in ('clear_results', 'start_spinner', 'update_timer'):
        setattr(app, name, Mock())
    thread = Mock()
    monkeypatch.setattr(module.threading, 'Thread', thread)
    app.search()
    assert thread.call_args.kwargs['args'][2] is False
    thread.return_value.start.assert_called_once()


def test_latest_identified_record_enables_browser_handoff():
    app = gui()
    app.publisher_button = Mock()
    app.import_pdf_button = Mock()
    record = {'title': 'Paper title', 'identifier': {'type': 'doi', 'value': '10.1234/paper'}, 'doi': '10.1234/paper'}
    app._update_results(DownloadResult(False, status='located', metadata=record))
    assert app._handoff_record == record
    app.publisher_button.configure.assert_called_with(state='normal')
    app.import_pdf_button.configure.assert_called_with(state='normal')


def test_open_publisher_is_explicit_and_uses_record_identity(monkeypatch):
    import gui as module
    app = gui()
    app._handoff_record = {'title': 'Paper title', 'doi': '10.1234/paper'}
    browser = Mock()
    monkeypatch.setattr(module.webbrowser, 'open', browser)
    app.open_publisher()
    browser.assert_called_once_with('https://doi.org/10.1234/paper')


def test_local_import_worker_only_invokes_offline_importer(monkeypatch):
    import sys
    from types import ModuleType
    module = ModuleType('src.acquisition.local_import')
    module.import_local_pdf = Mock(return_value=DownloadResult(False, status='mismatch'))
    monkeypatch.setitem(sys.modules, 'src.acquisition.local_import', module)
    app = gui()
    app.root = Mock()
    app.finder = Mock()
    app._search_id = 3
    record = {'title': 'Paper title', 'doi': '10.1234/paper'}
    app._import_pdf_thread(record, '/tmp/browser.pdf', '/tmp/papers', 3)
    module.import_local_pdf.assert_called_once_with(record, '/tmp/browser.pdf', '/tmp/papers')
    assert not app.finder.mock_calls
    assert app.root.after.called
