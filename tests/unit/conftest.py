"""Keep the default suite deterministic and prevent accidental external requests."""
import pytest
import requests


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Unit tests must mock HTTP; use tools/benchmark_identification.py --live for live metadata')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)


@pytest.fixture(autouse=True)
def isolated_provider_cooldowns(monkeypatch):
    """A mocked 429 must not throttle a different test or use yesterday's clock."""
    from src.core import discovery, provider_limits
    cooldowns = provider_limits.ProviderCooldowns()
    monkeypatch.setattr(provider_limits, 'provider_cooldowns', cooldowns)
    monkeypatch.setattr(discovery, 'provider_cooldowns', cooldowns)
    monkeypatch.setattr(discovery, '_SEMANTIC_NEXT_ALLOWED', 0.0)


@pytest.fixture(autouse=True)
def isolated_discovery_cache(monkeypatch):
    """Unit fixtures must neither read nor contaminate the user's metadata cache."""
    monkeypatch.setenv('PAPER_FINDER_CACHE', '0')
