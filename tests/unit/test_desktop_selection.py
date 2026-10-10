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
