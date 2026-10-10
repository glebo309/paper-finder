"""Legacy adapters must consume current metadata and documented response shapes."""
from unittest.mock import Mock


def test_deep_crawl_uses_canonical_plural_authors():
    from src.acquisition.deep_crawler import extract_author_info
    assert extract_author_info({'authors': ['John Smith', 'Jane Doe']}) == [
        {'name': 'John Smith', 'affiliation': ''}, {'name': 'Jane Doe', 'affiliation': ''}]


def test_international_cyberleninka_unpacks_url_title_pairs(monkeypatch):
    from src.acquisition import international_sources as module
    monkeypatch.setattr(module, 'search_cyberleninka', lambda *args: [('https://cyberleninka.ru/article.pdf', 'Expected title')])
    assert module.search_international_sources('Expected title', '10.1234/test', countries=['RU']) == [
        ('CyberLeninka', 'https://cyberleninka.ru/article.pdf')]


def test_figshare_fetches_article_detail_from_minimal_search_record():
    from src.acquisition.repositories import try_figshare
    session = Mock()
    session.post.return_value = Mock(status_code=200)
    session.post.return_value.json.return_value = [{'id': 123, 'title': 'A precise enzyme engineering study'}]
    session.get.return_value = Mock(status_code=200)
    session.get.return_value.json.return_value = {
        'id': 123, 'title': 'A precise enzyme engineering study',
        'authors': [{'full_name': 'Jane Doe'}],
        'files': [{'name': 'article.pdf', 'is_link_only': False, 'download_url': 'https://files.figshare.com/123/article.pdf'}]}
    assert try_figshare('10.1234/test', 'A precise enzyme engineering study', ['Jane Doe'], session) == 'https://files.figshare.com/123/article.pdf'
    session.get.assert_called_once()


import pytest


@pytest.mark.parametrize('module_name,entry,strategies', [
    ('repositories', 'try_fetch_from_repositories', ['try_zenodo', 'try_figshare', 'try_osf_storage', 'try_institutional_repo_hunt', 'try_dataverse', 'try_dspace_eprints_generic']),
    ('preprints_enhanced', 'try_fetch_from_preprints_enhanced', ['try_crossref_preprint_relations', 'try_arxiv', 'try_biorxiv_medrxiv', 'try_europe_pmc', 'try_chemrxiv', 'try_ssrn', 'try_osf_preprints', 'try_hal', 'try_core_aggregator']),
])
def test_legacy_group_rejects_wrong_pdf_then_tries_next_strategy(monkeypatch, tmp_path, module_name, entry, strategies):
    import importlib
    module = importlib.import_module('src.acquisition.' + module_name)
    for i, name in enumerate(strategies):
        monkeypatch.setattr(module, name, Mock(return_value=f'https://example.org/{i}.pdf' if i < 2 else None))
    verify = Mock(side_effect=[{'status': 'mismatch'}, {'status': 'verified'}])
    monkeypatch.setattr('src.core.validation.verify_document_identity', verify)
    session = Mock()
    session.get.side_effect = [Mock(content=b'%PDF-wrong' + b'x' * 52000), Mock(content=b'%PDF-correct' + b'x' * 52000)]
    path = tmp_path / 'paper.pdf'
    assert getattr(module, entry)('10.1234/test', 'Exact main article title', ['Jane Doe'], path, session) is True
    assert session.get.call_count == 2
    assert path.read_bytes().startswith(b'%PDF-correct')
    assert verify.call_count == 2
    assert verify.call_args.args[1]['doi'] == '10.1234/test'
