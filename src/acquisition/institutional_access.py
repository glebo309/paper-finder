"""Institution-independent links for the user's normal authenticated browser.

The caller opens returned links explicitly. Authentication stays with the
publisher or library; this module does not open browsers, read cookies, collect
credentials, or make network requests.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import os
import re
from urllib.parse import quote, unquote, urlsplit


INSTITUTIONAL_HELP = (
    "Open the article in your normal browser and choose the publisher's institutional login, "
    "or use your library's official proxy or university VPN. Access depends on your institution's "
    "subscriptions and your affiliation. Switch edu-ID is a sign-in service; eduroam provides "
    "Wi-Fi access and does not itself grant journal subscriptions."
)


def _web_url(value, name):
    if not isinstance(value, str) or re.search(r'[\x00-\x1f\x7f]', value):
        raise ValueError(f'{name} must be an HTTP or HTTPS URL without embedded credentials.')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or re.search(r'\s', value)):
            raise ValueError
        parsed.port  # Validate a supplied port before handing the URL to a browser.
    except ValueError:
        raise ValueError(f'{name} must be an HTTP or HTTPS URL without embedded credentials.') from None
    return value


def validate_login_url(login_url):
    """Validate an optional official institutional login/help link."""
    if login_url in ('', None):
        return ''
    return _web_url(login_url, 'Library login URL')


def validate_proxy_template(proxy_template):
    """Require one {url} placeholder in the official proxy's path or query."""
    if proxy_template in ('', None):
        return ''
    if not isinstance(proxy_template, str) or proxy_template.count('{url}') != 1:
        raise ValueError('Library proxy template must contain exactly one {url} placeholder.')
    remainder = proxy_template.replace('{url}', '')
    if '{' in remainder or '}' in remainder:
        raise ValueError('The only supported library proxy placeholder is {url}.')
    example = proxy_template.replace('{url}', quote('https://doi.org/10.1234/example', safe=''))
    _web_url(example, 'Library proxy template')
    parsed = urlsplit(proxy_template)
    if '{url}' in parsed.netloc or '{url}' in parsed.fragment:
        raise ValueError('Put {url} in the library proxy path or query, not its hostname or fragment.')
    return proxy_template.strip()


@dataclass(frozen=True)
class InstitutionalAccessSettings:
    """Optional library configuration; no institution or proxy is inferred."""
    label: str = ''
    login_url: str = ''
    proxy_template: str = ''

    def __post_init__(self):
        label = self.label or ''
        if not isinstance(label, str) or re.search(r'[\x00-\x1f\x7f]', label):
            raise ValueError('Institution label must be plain text on one line.')
        object.__setattr__(self, 'label', label.strip())
        object.__setattr__(self, 'login_url', validate_login_url(self.login_url))
        object.__setattr__(self, 'proxy_template', validate_proxy_template(self.proxy_template))


def load_institutional_settings(config=None, environ=None):
    """Load a config object's institutional section or a mapping, then env.

    Explicit environment values override configuration; an empty environment
    value clears the setting. Validation errors are raised for the caller to
    display, rather than silently opening a different site.
    """
    environ = os.environ if environ is None else environ
    if isinstance(config, Mapping):
        section = config.get('institutional', config)
    else:
        section = getattr(config, 'institutional', config)
    values = {}
    for field, variable in (('label', 'PAPER_FINDER_LIBRARY_LABEL'),
                            ('login_url', 'PAPER_FINDER_LIBRARY_LOGIN'),
                            ('proxy_template', 'PAPER_FINDER_LIBRARY_PROXY')):
        configured = section.get(field, '') if isinstance(section, Mapping) else getattr(section, field, '')
        values[field] = environ[variable] if variable in environ else configured
    return InstitutionalAccessSettings(**values)


def _article_url(record):
    if not isinstance(record, Mapping):
        raise ValueError('Select a paper with a DOI or article URL first.')
    identifier = record.get('identifier') or {}
    identifier = identifier if isinstance(identifier, Mapping) else {}
    doi = record.get('doi') or (identifier.get('value') if identifier.get('type') == 'doi' else None)
    if doi:
        if not isinstance(doi, str):
            raise ValueError('The selected paper has an invalid DOI.')
        doi = doi.strip()
        if re.match(r'^https?://(?:dx\.)?doi\.org/', doi, re.I):
            doi = urlsplit(doi).path.lstrip('/')
        else:
            doi = re.sub(r'^doi:\s*', '', doi, flags=re.I)
        doi = unquote(doi)
        if not re.fullmatch(r'10\.\d{4,9}/[^\s"]+', doi, re.I):
            raise ValueError('The selected paper has an invalid DOI.')
        return 'https://doi.org/' + quote(doi, safe='/')
    for name in ('url', 'html_url'):
        if record.get(name):
            return _web_url(record[name], 'Article URL')
    if identifier.get('type') == 'arxiv' and re.fullmatch(
            r'(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?', str(identifier.get('value') or ''), re.I):
        return 'https://arxiv.org/abs/' + identifier['value']
    raise ValueError('Select a paper with a DOI or article URL first.')


def browser_access_url(record, proxy_template=''):
    """Return a canonical article link, optionally wrapped by an explicit proxy.

    The {url} value is percent-encoded once as a whole URL. An empty template
    leaves the normal publisher route available for browser sessions, campus
    access and university VPNs. login_url remains a separate navigation link.
    """
    target = _article_url(record)
    template = validate_proxy_template(proxy_template)
    return template.replace('{url}', quote(target, safe='')) if template else target
