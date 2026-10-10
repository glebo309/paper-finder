from unittest.mock import Mock
import requests
from src.core.identity import IdentityResolver

URL = 'https://journal.example/article/123'
TITLE = 'Reliable enzymes for sustainable chemistry'


def make_resolver(html='', content_type='text/html', status=200):
    response = Mock(status_code=status, headers={'Content-Type': content_type})
    response.iter_content.return_value = [html.encode()]
    session = Mock(headers={})
    session.get.return_value = response
    return IdentityResolver(session=session), response


def test_citation_metadata_without_doi_becomes_acquirable_url_record():
    resolver, response = make_resolver(f'''<meta name="citation_title" content="{TITLE}">
       <meta name="citation_author" content="Alice Smith"><meta name="citation_author" content="Bob Jones">
       <meta name="citation_publication_date" content="2023/05/01">
       <meta name="citation_journal_title" content="Enzyme Science">
       <meta name="citation_pdf_url" content="/article/123.pdf">''')
    result = resolver.resolve(URL)
    assert result['title'] == TITLE
    assert result['identifier'] == {'type': 'url', 'value': URL}
    assert result['authors'] == ['Alice Smith', 'Bob Jones']
    assert result['year'] == 2023
    assert result['journal'] == 'Enzyme Science'
    assert result['pdf_urls'] == ['https://journal.example/article/123.pdf']
    assert result['metadata_source'] == 'publisher_metadata'
    assert result['input_url'] == URL
    response.close.assert_called_once()


def test_html_doi_uses_verified_record_and_retains_pdf():
    resolver, _ = make_resolver(f'<meta name="citation_title" content="{TITLE}"><meta name="citation_doi" content="10.1234/example"><meta name="citation_pdf_url" content="https://cdn.example/a.pdf">')
    resolver._resolve_doi = Mock(return_value={'identifier': {'type': 'doi', 'value': '10.1234/example'}, 'doi': '10.1234/example', 'title': TITLE, 'sources': ['crossref']})
    result = resolver.resolve(URL)
    resolver._resolve_doi.assert_called_once_with('10.1234/example')
    assert result['doi'] == '10.1234/example'
    assert result['pdf_urls'] == ['https://cdn.example/a.pdf']
    assert result['input_url'] == URL


def test_generic_html_title_is_not_paper_identification():
    resolver, _ = make_resolver('<title>Sign in to publisher</title><meta property="og:title" content="Log in">')
    result = resolver.resolve(URL)
    assert result['status'] == 'not_found'
    assert not result['title']


def test_pdf_identification_does_not_download_pdf_body():
    resolver, response = make_resolver('%PDF-fake', content_type='application/pdf')
    result = resolver.resolve(URL)
    response.iter_content.assert_not_called()
    assert result['status'] == 'not_found'
    assert result['input_url'] == URL


def test_url_network_failure_is_unavailable_without_leaking_exception():
    resolver, _ = make_resolver()
    resolver.session.get.side_effect = requests.ConnectionError('sensitive URL value')
    result = resolver.resolve(URL)
    assert result['status'] == 'unavailable'
    assert 'sensitive URL value' not in str(result)


def test_oversized_html_is_rejected_and_response_closed():
    resolver, response = make_resolver()
    response.iter_content.return_value = [b'x' * (1024 * 1024 + 1)]
    result = resolver.resolve(URL)
    assert result['status'] == 'not_found'
    assert not result['title']
    response.close.assert_called_once()


def test_non_http_and_credential_pdf_links_are_excluded():
    resolver, _ = make_resolver(f'''<meta name="citation_title" content="{TITLE}">
      <meta name="citation_pdf_url" content="file:///secret.pdf">
      <meta name="citation_pdf_url" content="https://user:pass@example.com/x.pdf">
      <meta name="citation_pdf_url" content="javascript:alert(1)">''')
    assert resolver.resolve(URL)['pdf_urls'] == []


def test_failed_doi_lookup_is_not_hidden_by_html_title():
    resolver, _ = make_resolver(f'<meta name="citation_title" content="{TITLE}"><meta name="citation_doi" content="10.1234/example">')
    resolver._resolve_doi = Mock(return_value={'identifier': {'type': None, 'value': None}, 'status': 'unavailable', 'error': 'Unavailable'})
    result = resolver.resolve(URL)
    assert result['status'] == 'unavailable'
    assert result['input_url'] == URL


def test_redirect_is_followed_with_relative_pdf_based_on_final_url():
    resolver, response = make_resolver(f'<meta name="citation_title" content="{TITLE}"><meta name="citation_pdf_url" content="paper.pdf">')
    redirect = Mock(status_code=302, headers={'Location': '/new/article'})
    resolver.session.get.side_effect = [redirect, response]
    result = resolver.resolve(URL)
    assert result['pdf_urls'] == ['https://journal.example/new/paper.pdf']
    redirect.close.assert_called_once()


def test_redirect_loop_stops_and_closes_each_response():
    resolver, _ = make_resolver()
    responses = [Mock(status_code=302, headers={'Location': '/again'}) for _ in range(4)]
    resolver.session.get.side_effect = responses
    result = resolver.resolve(URL)
    assert resolver.session.get.call_count == 4
    assert result['status'] == 'unavailable'
    for response in responses:
        response.close.assert_called_once()


def test_conflicting_dois_do_not_choose_first_tag():
    resolver, _ = make_resolver(f'<meta name="citation_title" content="{TITLE}"><meta name="citation_doi" content="10.1234/one"><meta name="citation_doi" content="10.1234/two">')
    resolver._resolve_doi = Mock()
    result = resolver.resolve(URL)
    assert result['status'] == 'ambiguous'
    resolver._resolve_doi.assert_not_called()


def test_malformed_explicit_doi_is_not_replaced_by_title_identity():
    resolver, _ = make_resolver(f'<meta name="citation_title" content="{TITLE}"><meta name="citation_doi" content="malformed">')
    assert resolver.resolve(URL)['status'] == 'not_found'
