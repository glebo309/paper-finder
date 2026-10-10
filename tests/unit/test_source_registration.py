from unittest.mock import Mock

from paper_finder import PaperFinder
from src.core.config import Config


def test_disabled_telegram_cannot_be_reenabled_by_dynamic_registration():
    config = Config()
    config.cache.enabled = False
    config.telegram.underground_enabled = False
    config.telegram.api_id = 12345
    config.telegram.api_hash = 'test-only-placeholder'
    finder = PaperFinder(config=config, silent_init=True)
    assert 'Telegram Bots' not in finder.pipeline.get_registered_sources()


def test_incomplete_telegram_credentials_do_not_register(monkeypatch):
    monkeypatch.delenv('TELEGRAM_API_HASH', raising=False)
    config = Config()
    config.cache.enabled = False
    config.telegram.underground_enabled = True
    config.telegram.api_id = 12345
    config.telegram.api_hash = None
    finder = PaperFinder(config=config, silent_init=True)
    assert 'Telegram Bots' not in finder.pipeline.get_registered_sources()


def test_telegram_wrapper_uses_explicit_configured_bot_names(monkeypatch, tmp_path):
    config = Config()
    config.cache.enabled = False
    config.telegram.underground_enabled = True
    config.telegram.api_id = 12345
    config.telegram.api_hash = 'test-only-placeholder'
    config.telegram.underground_bots = ['@configured_example_bot']
    finder = PaperFinder(config=config, silent_init=True)
    factory = Mock()
    factory.return_value.try_acquire.return_value = Mock(success=False, error='not contacted')
    monkeypatch.setattr('src.acquisition.telegram_underground.TelegramUndergroundSource', factory)
    finder._try_telegram_underground('10.1234/test', tmp_path/'out.pdf', {})
    assert factory.call_args.kwargs['bots'] == ['@configured_example_bot']
