"""Cooldowns coordinate retries without sleeping or making requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from src.core import provider_limits
from src.core.provider_limits import ProviderCooldowns


def test_numeric_retry_after_expires_on_monotonic_deadline():
    limits = ProviderCooldowns()
    assert limits.remaining('crossref', now=100) == 0
    assert limits.record_limit('crossref', '30', now=100) == 30
    assert limits.remaining('crossref', now=112) == 18
    assert limits.remaining('crossref', now=131) == 0


def test_openalex_search_families_share_one_cooldown():
    limits = ProviderCooldowns()
    limits.record_limit('openalex_semantic', 45, now=100)
    for provider in ('openalex', 'openalex_citation', 'openalex_semantic'):
        assert limits.remaining(provider, now=101) == 44
    assert limits.remaining('crossref', now=101) == 0
    assert limits.remaining('semantic_scholar', now=101) == 0


@pytest.mark.parametrize('value', [None, '', 'not a date', 'NaN', 'Infinity', float('nan')])
def test_missing_or_invalid_retry_after_defaults_to_sixty_seconds(value):
    assert ProviderCooldowns().record_limit('crossref', value, now=100) == 60


@pytest.mark.parametrize('value', ['0', '-4', '.1'])
def test_retry_delay_is_at_least_one_second(value):
    assert ProviderCooldowns().record_limit('crossref', value, now=100) == 1


def test_valid_long_retry_delay_is_never_truncated():
    limits = ProviderCooldowns()
    assert limits.record_limit('openalex', '39992', now=100) == 39992
    assert limits.remaining('openalex_semantic', now=101) == 39991


def test_http_date_converts_wall_time_to_monotonic_deadline(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(provider_limits, 'datetime', FrozenDatetime)
    limits = ProviderCooldowns()
    assert limits.record_limit('crossref', 'Sat, 10 Oct 2026 12:02:00 GMT', now=500) == 120
    assert limits.remaining('crossref', now=550) == 70
    assert ProviderCooldowns().record_limit('crossref', 'Sat, 10 Oct 2026 11:00:00 GMT', now=500) == 1


def test_omitted_now_uses_monotonic_clock(monkeypatch):
    monkeypatch.setattr(provider_limits.time, 'monotonic', lambda: 100)
    limits = ProviderCooldowns()
    limits.record_limit('crossref', 10)
    monkeypatch.setattr(provider_limits.time, 'monotonic', lambda: 104)
    assert limits.remaining('crossref') == 6


def test_concurrent_limits_never_shorten_existing_provider_deadline():
    limits = ProviderCooldowns()
    delays = [1, 60, 3600, 12, 150, 2, 600, 30]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda delay: limits.record_limit('openalex', delay, now=100), delays))
    assert limits.remaining('openalex_citation', now=100) == 3600
    assert limits.record_limit('openalex_semantic', 1, now=101) == 3599


def test_module_wrappers_use_shared_instance(monkeypatch):
    monkeypatch.setattr(provider_limits, 'provider_cooldowns', ProviderCooldowns())
    assert provider_limits.record_limit('crossref', 20, now=100) == 20
    assert provider_limits.remaining('crossref', now=105) == 15
