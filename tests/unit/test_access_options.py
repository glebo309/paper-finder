from unittest.mock import Mock


def test_repository_copies_are_combined_with_index_results():
    from src.acquisition.access_options import discover_access_options
    recent = Mock()
    recent.discover.return_value = {'doi':'10.1234/test','locations':[], 'alternatives':[], 'errors':{'publisher':{'kind':'http','status':403}}}
    repository = Mock()
    location = {'url':'https://hal.example/paper.pdf','pdf_url':'https://hal.example/paper.pdf','version':'acceptedVersion','source':'hal','downloadable':True}
    repository.discover.return_value = {'locations':[location], 'alternatives':[], 'errors':{}}
    record = {'doi':'10.1234/test','title':'A precise enzyme paper','authors':['Jane Doe']}
    result = discover_access_options(record, recent=recent, repositories=repository)
    assert result['locations'] == [location]
    assert result['errors']['publisher']['status'] == 403
    assert result['status'] == 'found'
    repository.discover.assert_called_once_with(record)


def test_conflicting_version_url_never_reenters_downloadable_locations():
    from src.acquisition.access_options import merge_access_reports
    pdf = 'https://repo.example/article.pdf'
    result = merge_access_reports({'locations':[{'url':pdf,'pdf_url':pdf,'version':'acceptedVersion'}]},
                                  {'alternatives':[{'url':pdf,'pdf_url':pdf,'version':'submittedVersion','record':{'title':'Preprint'}}]})
    assert not result['locations']
    assert any(item['version'] == 'conflicting' and item['requires_selection'] for item in result['alternatives'])


def test_repository_failure_does_not_discard_existing_pdf():
    from src.acquisition.access_options import discover_access_options
    recent = Mock()
    recent.discover.return_value = {'locations':[{'url':'https://example.org/file.pdf'}], 'errors':{}}
    repository = Mock()
    repository.discover.side_effect = ValueError('provider broke')
    result = discover_access_options({'doi':'10.1234/test'}, recent=recent, repositories=repository)
    assert len(result['locations']) == 1
    assert result['errors']['repositories']['kind'] == 'error'
