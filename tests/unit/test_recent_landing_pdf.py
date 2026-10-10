"""Resolve only explicitly advertised full-text PDF links on open landing pages."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests

from src.acquisition.recent_open_access import discover_landing_pdf

LOCATION = {'doi': '10.1234/new', 'url': 'https://repository.edu/record/42',
            'landing_page_url': 'https://repository.edu/record/42', 'pdf_url': None,
            'availability': 'open', 'version': 'acceptedVersion', 'license': 'cc-by',
            'requires_selection': False, 'downloadable': False,
            'sources': ['unpaywall'], 'provenance': [{'provider': 'unpaywall'}]}


def response(html='', *, url=LOCATION['url'], content_type='text/html', status=200, headers=None):
    result = Mock(status_code=status, url=url, headers={'Content-Type': content_type, **(headers or {})})
    result.iter_content.return_value = [html.encode()]
    return result


def test_citation_pdf_relative_url_preserves_identity_version_and_original():
    original = deepcopy(LOCATION)
    session = Mock()
    session.get.return_value = response('<meta name="citation_doi" content="10.1234/new"><meta name="citation_pdf_url" content="../../download/42">')
    result = discover_landing_pdf(LOCATION, session=session)
    assert result['pdf_url'] == 'https://repository.edu/download/42'
    assert result['version'] == 'acceptedVersion'
    assert result['downloadable'] is True
    assert result['provenance'][-1]['provider'] == 'landing_page'
    assert LOCATION == original
    session.get.return_value.close.assert_called_once()


def test_alternate_pdf_link_uses_final_redirect_url():
    session = Mock()
    redirect = response(status=302, headers={'Location': 'https://repo2.edu/records/article'})
    page = response('<link rel="alternate" type="application/pdf" href="file">', url='https://repo2.edu/records/article')
    session.get.side_effect = [redirect, page]
    result = discover_landing_pdf(LOCATION, session=session)
    assert result['pdf_url'] == 'https://repo2.edu/records/file'
    assert session.get.call_count == 2
    redirect.close.assert_called_once()
    page.close.assert_called_once()


def test_pdf_content_type_does_not_read_body():
    session = Mock()
    pdf = response(content_type='application/pdf', url='https://repo.edu/download/file')
    session.get.return_value = pdf
    assert discover_landing_pdf(LOCATION, session=session)['pdf_url'] == pdf.url
    pdf.iter_content.assert_not_called()
    pdf.close.assert_called_once()


@pytest.mark.parametrize('html', [
    '<a href="supplement.pdf">PDF</a>',
    '<link rel="alternate" type="application/pdf" title="Supporting information" href="supp.pdf">',
    '<meta name="citation_doi" content="10.1234/wrong"><meta name="citation_pdf_url" content="file.pdf">',
    '<meta name="citation_pdf_url" content="file:///private/file.pdf">',
    '<meta name="citation_pdf_url" content="https://user:pass@host.edu/file.pdf">',
    '<title>Verify you are human</title><meta name="citation_pdf_url" content="file.pdf">',
    '<title>Sign in</title><meta name="citation_pdf_url" content="file.pdf">',
])
def test_does_not_guess_download_or_read_login_and_challenge_pages(html):
    session = Mock()
    session.get.return_value = response(html)
    assert discover_landing_pdf(LOCATION, session=session) is None


@pytest.mark.parametrize('change', [
    {'availability': 'closed'}, {'availability': 'embargoed'},
    {'requires_selection': True}, {'landing_page_url': 'file:///tmp/record'},
])
def test_ineligible_locations_make_no_request(change):
    session = Mock()
    assert discover_landing_pdf({**LOCATION, **change}, session=session) is None
    session.get.assert_not_called()


def test_size_limit_and_response_cleanup():
    session = Mock()
    page = response('<meta name="citation_pdf_url" content="file.pdf">' + 'x'*1000)
    session.get.return_value = page
    assert discover_landing_pdf(LOCATION, session=session, max_bytes=100) is None
    page.close.assert_called_once()


def test_redirects_are_bounded_and_unsafe_redirect_not_followed():
    session = Mock()
    page = response(status=302, headers={'Location': LOCATION['url']})
    session.get.return_value = page
    assert discover_landing_pdf(LOCATION, session=session) is None
    assert session.get.call_count <= 4
    session.reset_mock()
    page.headers['Location'] = 'file:///tmp/record'
    assert discover_landing_pdf(LOCATION, session=session) is None
    assert session.get.call_count == 1


def test_network_error_is_unsuccessful_without_exception_leak():
    session = Mock()
    session.get.side_effect = requests.Timeout('url with credentials')
    assert discover_landing_pdf(LOCATION, session=session) is None
