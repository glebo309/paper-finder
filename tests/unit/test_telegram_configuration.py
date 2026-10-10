"""Only constructor behavior; no client, authentication or messages are used."""
from unittest.mock import Mock
import pytest


def create(monkeypatch, **kwargs):
    import src.acquisition.telegram_underground as module
    monkeypatch.setattr(module, 'TELETHON_AVAILABLE', True)
    return module.TelegramUndergroundSource(session=Mock(), api_id=12345, api_hash='not-used', **kwargs)


def test_custom_bot_list_is_respected_and_deduplicated_without_client(monkeypatch):
    source = create(monkeypatch, bots=['@configured_bot','@another_bot','@configured_bot'])
    assert source.bots == ['@configured_bot','@another_bot']
    assert source.client is None
    assert source.enabled


def test_empty_bot_list_disables_source(monkeypatch):
    source = create(monkeypatch, bots=[])
    assert source.bots == []
    assert not source.enabled


@pytest.mark.parametrize('bots', ['@not_a_list', ['https://t.me/example'], [42], ['@a'], ['@name with spaces']])
def test_invalid_bot_configuration_rejected_before_any_client(monkeypatch,bots):
    with pytest.raises(ValueError, match='bot'):
        create(monkeypatch,bots=bots)
