"""Institution-independent browser links, without authentication side effects."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from src.acquisition.institutional_access import (
    InstitutionalAccessSettings, browser_access_url, load_institutional_settings,
    validate_login_url, validate_proxy_template,
)

RECORD = {'doi': '10.1002/chem.71699', 'url': 'https://metadata.example/record'}


def test_default_browser_url_is_canonical_publisher_doi():
    assert browser_access_url(RECORD) == 'https://doi.org/10.1002/chem.71699'


def test_record_identifier_and_opaque_doi_are_supported():
    url = browser_access_url({'identifier': {'type': 'doi', 'value': '10.1002/(SICI)123<1::AID-TEST>2.0.CO;2-1'}})
    assert url == 'https://doi.org/10.1002/%28SICI%29123%3C1%3A%3AAID-TEST%3E2.0.CO%3B2-1'


def test_proxy_template_encodes_exact_target_url_once():
    url = browser_access_url(RECORD, 'https://library.example/login?url={url}')
    assert url == 'https://library.example/login?url=https%3A%2F%2Fdoi.org%2F10.1002%2Fchem.71699'
    assert parse_qs(urlsplit(url).query)['url'] == ['https://doi.org/10.1002/chem.71699']


def test_direct_record_url_keeps_query_and_proxy_does_not_inject_query_parameters():
    record = {'url': 'https://publisher.example/article?a=one&b=two#fulltext'}
    assert browser_access_url(record) == record['url']
    parsed = parse_qs(urlsplit(browser_access_url(record, 'https://library.example/login?url={url}')).query)
    assert parsed == {'url': [record['url']]}


def test_default_does_not_guess_proxy_from_institution_label():
    settings = InstitutionalAccessSettings(label='An arbitrary university')
    assert settings.proxy_template == ''
    assert settings.login_url == ''
    assert browser_access_url(RECORD, settings.proxy_template).startswith('https://doi.org/')


@pytest.mark.parametrize('template', [
    'https://library.example/login', 'https://library.example/{url}/{url}',
    'https://library.example/?url={other}', 'https://library.example/?url={url}&x={secret}',
    'javascript:{url}', 'file:///tmp/{url}', 'https://user:password@library.example/?url={url}',
    'https://{url}.example/login', 'https://library.example/#url={url}',
    'https://library.example/\n?url={url}',
])
def test_bad_proxy_template_is_rejected(template):
    with pytest.raises(ValueError):
        validate_proxy_template(template)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///tmp/login', '//library.example/login',
    'https://user:pass@library.example/login', 'https://library.example/login\n',
    'https://library.example:wrong/login'])
def test_login_url_validation(url):
    with pytest.raises(ValueError):
        validate_login_url(url)


def test_optional_login_link_is_separate_from_article_access():
    settings = InstitutionalAccessSettings(login_url='https://library.example/remote-access')
    assert settings.login_url == 'https://library.example/remote-access'
    assert browser_access_url(RECORD, settings.proxy_template) == 'https://doi.org/10.1002/chem.71699'


def test_environment_overrides_config_explicitly_and_can_clear_fields():
    settings = load_institutional_settings({'institutional': {'label': 'Configured',
        'login_url': 'https://old.example/login', 'proxy_template': 'https://old.example/?url={url}'}},
        environ={'PAPER_FINDER_LIBRARY_LABEL':'New', 'PAPER_FINDER_LIBRARY_LOGIN':'',
                 'PAPER_FINDER_LIBRARY_PROXY':'https://new.example/?url={url}'})
    assert settings.label == 'New'
    assert settings.login_url == ''
    assert settings.proxy_template == 'https://new.example/?url={url}'


def test_load_settings_accepts_config_object_and_raw_section():
    expected = InstitutionalAccessSettings(label='University', login_url='https://library.example/')
    assert load_institutional_settings(SimpleNamespace(institutional=expected), environ={}) == expected
    assert load_institutional_settings({'label':'University', 'login_url':'https://library.example/'}, environ={}) == expected


def test_missing_configuration_is_optional(monkeypatch):
    for key in ('PAPER_FINDER_LIBRARY_LABEL','PAPER_FINDER_LIBRARY_LOGIN','PAPER_FINDER_LIBRARY_PROXY'):
        monkeypatch.delenv(key, raising=False)
    assert load_institutional_settings() == InstitutionalAccessSettings()
    assert validate_login_url('') == ''
    assert validate_proxy_template('') == ''


@pytest.mark.parametrize('record', [None, {}, {'doi':'find a paper about catalysis'},
    {'url':'file:///private/secret'}, {'url':'https://user:pass@publisher.example/paper'}])
def test_invalid_article_identity_or_url_raises_actionable_error(record):
    with pytest.raises(ValueError):
        browser_access_url(record)


def test_no_doi_can_use_an_arxiv_record():
    assert browser_access_url({'identifier': {'type':'arxiv','value':'1706.03762v7'}}) == 'https://arxiv.org/abs/1706.03762v7'
