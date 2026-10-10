"""Offline source inventory: configuration availability is not live coverage."""
import importlib.util
import os
import re


def _installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _field(config, section, name, default=None):
    group = config.get(section, {}) if isinstance(config, dict) else getattr(config, section, None)
    return group.get(name, default) if isinstance(group, dict) else getattr(group, name, default)


def source_status(config=None, *, environ=None):
    """Return JSON-safe local status without requests, adapter imports or login.

    ``available`` and ``configured`` mean prerequisites appear present locally.
    All rows remain ``not_live_revalidated``; this function never claims an API,
    scraper or bot currently returns a verified document. Secret values, contact
    addresses and session paths are deliberately excluded from the report.
    """
    if config is None:
        from .config import Config
        config = Config()
    env = os.environ if environ is None else environ
    rows = []

    def add(key, name, category, notes, *, dependencies=('requests',), credentials=None,
            required=(), enabled=True, route='legacy_acquisition'):
        dependencies = {dep: _installed(dep) for dep in dependencies}
        credentials = credentials or {}
        configured = any(credentials.values()) and all(credentials.get(key, False) for key in required)
        if not enabled:
            status = 'disabled'
        elif not all(dependencies.values()):
            status = 'dependency_missing'
        elif any(not credentials.get(key, False) for key in required):
            status = 'requires_credentials'
        elif any(credentials.values()):
            status = 'configured'
        else:
            status = 'available'
        row = {'id':key, 'name':name, 'category':category, 'status':status,
               'enabled':bool(enabled), 'configured':configured,
               'credentials_present':credentials, 'dependencies':dependencies,
               'validation':'not_live_revalidated', 'route':route, 'notes':list(notes)}
        rows.append(row)
        return row

    add('openalex', 'OpenAlex', 'metadata and current copies',
        ['Public metadata path; an optional API key affects access and quota. Availability of any particular copy is not checked here.'],
        credentials={'api_key':bool(env.get('OPENALEX_API_KEY'))}, route='discovery_and_recent_sources')
    add('crossref', 'Crossref', 'metadata and publisher links',
        ['Bibliographic discovery and DOI-linked document locations; a metadata match is not a downloaded paper.'],
        credentials={'contact_address':bool(env.get('CROSSREF_MAILTO'))}, route='discovery_and_fallback')
    add('europepmc', 'Europe PMC', 'metadata and current copies',
        ['Biomedical metadata and full-text locations; manuscript versions and access labels require inspection.'], route='discovery_and_recent_sources')
    add('semanticscholar', 'Semantic Scholar', 'metadata and copies',
        ['Public fallback with optional API key; quotas and coverage are not tested by this inventory.'],
        credentials={'api_key':bool(_field(config,'api','semantic_scholar_api_key') or env.get('SEMANTIC_SCHOLAR_API_KEY'))}, route='discovery_and_fallback')
    email = _field(config, 'api', 'unpaywall_email') or env.get('UNPAYWALL_EMAIL')
    # The legacy placeholder is not a configured contact address.
    if email == 'test@test.com':
        email = env.get('UNPAYWALL_EMAIL')
    valid_email = isinstance(email,str) and email.lower() != 'test@test.com' and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email))
    add('unpaywall', 'Unpaywall', 'current copies',
        ['Requires a contact email. Reports publisher/repository locations, versions and embargo information when indexed.'],
        credentials={'contact_email':bool(valid_email)}, required=('contact_email',), route='recent_sources_and_fallback')
    add('core', 'CORE.ac.uk', 'repository aggregation',
        ['The current adapter requires CORE_API_KEY and returns no URLs when it is absent.'],
        credentials={'api_key':bool(env.get('CORE_API_KEY'))}, required=('api_key',))
    add('pmc', 'PubMed Central', 'repository', ['PMC repository and cloud adapters; document retrieval and identity still need verification.'])
    add('arxiv', 'arXiv / bioRxiv / medRxiv', 'preprint repositories',
        ['Exact preprint identifiers have direct routes. A preprint is a distinct version, not an automatic journal-paper replacement.'], route='explicit_identifier')
    add('repositories', 'Open Repositories', 'repository aggregation',
        ['Legacy searches include Zenodo, Figshare, OSF, Dataverse and institutional repositories. Endpoint coverage has not been revalidated.'], dependencies=('requests','bs4'))
    add('direct_repositories', 'HAL / Zenodo direct search', 'author manuscripts and repository copies',
        ['Bounded exact-DOI and title/author searches with explicit version and relation evidence.',
         'Different or uncertain manuscript identities remain alternatives with their own selectable records.'], route='direct_repository_discovery')
    add('preprints', 'Preprints Enhanced', 'preprint and author manuscripts',
        ['Legacy candidates include arXiv, bioRxiv, medRxiv, ChemRxiv, SSRN, OSF, HAL and Crossref relations.',
         'Independent preprint/author-version searches remain in the fallback. Known alternate versions require explicit selection; identity checks prevent silent substitution.'], dependencies=('requests','bs4'))
    for key, name, note in (
        ('scihub', 'SciHub', 'Legacy mirror adapter; configured domains do not establish reachability, coverage or successful downloads.'),
        ('annas_archive', "Anna's Archive", 'Legacy paper/book lookup. A browser link does not count as a verified download.'),
        ('libgen', 'LibGen', 'Legacy DOI and book lookup; current mirrors and results have not been revalidated.')):
        add(key,name,'legacy library', [note], dependencies=('requests','bs4'))
    telegram_enabled = bool(_field(config,'telegram','underground_enabled',False))
    bots = _field(config,'telegram','underground_bots',[]) or []
    bots = [bot for bot in bots if isinstance(bot,str) and re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}',bot)] if isinstance(bots,list) else []
    telegram = add('telegram','Telegram Bots','messaging integration',
        ['Explicit enablement, API ID/hash and Telethon are required. Configured bot names are listed without contacting them.',
         'This check does not log in, inspect a session, validate bot availability or send messages.'],
        dependencies=('requests','telethon'), credentials={
            'api_id':bool(_field(config,'telegram','api_id') or env.get('TELEGRAM_API_ID')),
            'api_hash':bool(_field(config,'telegram','api_hash') or env.get('TELEGRAM_API_HASH'))},
        required=('api_id','api_hash'),enabled=telegram_enabled and bool(bots),route='explicitly_enabled_messaging')
    telegram['configured_bots'] = bots
    if telegram_enabled and not bots:
        telegram['notes'].append('No valid bot names are configured.')
    for key,name,note in (
        ('international','International','Legacy searches include CyberLeninka, HAL, SciELO, Dialnet, Korean and Iranian sources. Implemented endpoints are not proof of current coverage.'),
        ('multilang','Multi-language','The registered wrapper immediately returns False: translated-title acquisition is disabled. The underlying Baidu, Yandex and Naver code is not active in that route.'),
        ('chinese','Chinese Sources','Legacy CNKI, Wanfang, VIP and university searches. Subscription access and scraping behavior are not tested here.'),
        ('google_scholar','Google Scholar','Legacy search extraction; anti-automation restrictions and current parsing are not tested here.'),
        ('publisher','Publisher / landing-page adapters','Publisher patterns, landing-page parsing and legacy access adapters. No claim that access restrictions can be bypassed.'),
        ('deep_crawl','Deep Crawl','Legacy broader link discovery; document identity checks remain required.')):
        add(key,name,'legacy web discovery',[note],dependencies=('requests','bs4'),enabled=key != 'multilang')
    library = bool(_field(config,'institutional','proxy_template') or _field(config,'institutional','login_url') or env.get('PAPER_FINDER_LIBRARY_PROXY') or env.get('PAPER_FINDER_LIBRARY_LOGIN'))
    add('browser','Browser and institutional handoff','user browser',
        ['Uses the browser for sign-in and PDF downloading. Local import/watch verifies the file; no passwords or browser sessions are copied.'],
        dependencies=(), credentials={'institution_settings':library},route='explicit_browser_action')
    parallel = bool(_field(config, 'pipeline', 'parallel_execution', True))
    for row in rows:
        if row['id'] == 'browser':
            row['acquisition_scheduling'] = 'explicit_user_action'
        elif row['status'] in ('available', 'configured'):
            row['acquisition_scheduling'] = 'parallel_race' if parallel else 'sequential'
            row['notes'].append('When eligible for acquisition, this route joins the parallel race; the first verified PDF wins and rejected candidates do not stop other routes.' if parallel else
                                'Sequential acquisition is configured; a verified PDF ends the search.')
        else:
            row['acquisition_scheduling'] = 'not_ready'
    return rows
