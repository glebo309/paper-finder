import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `import src...` works in tests
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def app_config(tmp_path) -> SimpleNamespace:
    """Mocked AppConfig-like object with no real disk I/O."""
    network = SimpleNamespace(
        timeout_short=5,
        timeout_medium=15,
        timeout_long=60,
        max_workers=3,
    )

    validation = SimpleNamespace(
        min_size_kb=50,
    )

    cache = SimpleNamespace(
        enabled=False,
        cache_file=tmp_path / "paper_finder_cache.json",
        max_age_hours=24,
    )

    scihub = SimpleNamespace(
        domains=["https://sci-hub.se"],
        check_reachability=True,
        cache_working_domain=True,
    )

    api = SimpleNamespace(
        unpaywall_email="test@example.com",
        semantic_scholar_api_key=None,
    )

    pipeline = SimpleNamespace(
        parallel_execution=True,
        fast_oa_check=True,
        stop_on_browser_open=True,
        method_timeout=60,
        record_attempts=True,
    )

    return SimpleNamespace(
        network=network,
        validation=validation,
        cache=cache,
        scihub=scihub,
        api=api,
        pipeline=pipeline,
    )


@pytest.fixture
def mock_smart_cache():
    """Mocked SmartCache that never touches disk."""

    class MockSmartCache:
        def __init__(self):
            self.recorded = []
            self.best_methods = {}

        def record_attempt(self, publisher: str, year: int, method: str, success: bool):
            self.recorded.append(
                {
                    "publisher": publisher,
                    "year": year,
                    "method": method,
                    "success": success,
                }
            )

        def get_best_methods(self, publisher: str, top_n: int = 3):
            methods = self.best_methods.get(publisher, [])
            return methods[:top_n]

    return MockSmartCache()


@pytest.fixture
def valid_doi() -> str:
    """A DOI that we will treat as 'valid' in tests (responses will mock it)."""
    return "10.1234/example.doi"


@pytest.fixture
def invalid_doi() -> str:
    """A DOI that we will treat as 'invalid' or failing in tests."""
    return "10.9999/nonexistent.doi"


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Temporary clean output directory for tests that need to write files."""
    out = tmp_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out
