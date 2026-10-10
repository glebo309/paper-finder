"""Keep the default suite deterministic and prevent accidental external requests."""
import pytest
import requests


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Unit tests must mock HTTP; use tools/benchmark_identification.py --live for live metadata')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)
