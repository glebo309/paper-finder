"""Source diagnostics inspect local configuration without starting adapters."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.core.config import Config
from src.core.source_status import source_status


def row(rows, name):
    return next(item for item in rows if item['id'] == name)


def test_disabled_telegram_is_visible_without_leaking_credentials(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    config = Config()
    config.telegram.underground_enabled = False
    config.telegram.api_id = '12345'
    config.telegram.api_hash = 'SECRET_HASH'
    config.telegram.phone = '+SECRET_PHONE'
    rows = source_status(config, environ={'CORE_API_KEY':'SECRET_CORE', 'UNPAYWALL_EMAIL':'private@example.org'})
    telegram = row(rows, 'telegram')
    assert telegram['status'] == 'disabled'
    assert not telegram['enabled']
    assert telegram['credentials_present']['api_hash'] is True
    text = json.dumps(rows)
    assert 'SECRET' not in text and 'private@example.org' not in text
    assert all(item['validation'] == 'not_live_revalidated' for item in rows)


def test_missing_credentials_and_dependencies_are_distinguished(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    config = Config()
    config.telegram.underground_enabled = True
    config.telegram.api_id = None
    config.telegram.api_hash = None
    config.api.unpaywall_email = 'test@test.com'
    rows = source_status(config, environ={})
    assert row(rows, 'telegram')['status'] == 'requires_credentials'
    assert row(rows, 'unpaywall')['status'] == 'requires_credentials'
    assert row(rows, 'core')['status'] == 'requires_credentials'
    monkeypatch.setattr('src.core.source_status._installed', lambda name: name != 'telethon')
    assert row(source_status(config, environ={}), 'telegram')['status'] == 'dependency_missing'


def test_configured_telegram_reports_configured_list_without_claiming_live_success(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    config = Config()
    config.telegram.underground_enabled = True
    config.telegram.api_id = '12345'
    config.telegram.api_hash = 'secret'
    config.telegram.underground_bots = ['@configured_bot']
    telegram = row(source_status(config, environ={}), 'telegram')
    assert telegram['status'] == 'configured'
    assert telegram['configured_bots'] == ['@configured_bot']
    assert telegram['validation'] == 'not_live_revalidated'
    assert 'working' not in ' '.join(telegram['notes']).lower()


def test_optional_keys_do_not_hide_public_and_foreign_sources(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    rows = source_status(Config(), environ={})
    for name in ('openalex', 'crossref', 'europepmc', 'international', 'chinese', 'repositories', 'direct_repositories'):
        assert row(rows, name)['status'] == 'available'
    assert row(rows, 'multilang')['status'] == 'disabled'
    assert 'HAL' in ' '.join(row(rows, 'international')['notes'])
    assert 'preprint' in ' '.join(row(rows, 'preprints')['notes']).lower()


def test_status_only_checks_dependencies_never_imports_adapter(monkeypatch):
    import sys
    adapter = Mock(side_effect=AssertionError('Do not initialize adapters'))
    monkeypatch.setitem(sys.modules, 'paper_finder', SimpleNamespace(PaperFinder=adapter))
    source_status(Config(), environ={})
    adapter.assert_not_called()


def test_explicit_empty_bot_list_is_disabled(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    config = Config()
    config.telegram.underground_enabled = True
    config.telegram.api_id = 12345
    config.telegram.api_hash = 'secret'
    config.telegram.underground_bots = []
    telegram = row(source_status(config, environ={}), 'telegram')
    assert telegram['status'] == 'disabled'
    assert telegram['configured_bots'] == []


def test_unconfigured_optional_credentials_are_not_labelled_configured(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    assert row(source_status(Config(), environ={}), 'openalex')['configured'] is False


def test_inventory_scheduling_matches_configured_acquisition_mode(monkeypatch):
    monkeypatch.setattr('src.core.source_status._installed', lambda name: True)
    config = Config()
    entry = row(source_status(config,environ={}), 'international')
    assert entry['acquisition_scheduling'] == 'parallel_race'
    assert any('first verified' in note.lower() for note in entry['notes'])
    config.pipeline.parallel_execution = False
    assert row(source_status(config,environ={}), 'international')['acquisition_scheduling'] == 'sequential'
