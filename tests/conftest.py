"""Shared fixtures: tmp working dir + defensive FMP blocker."""
import sys
from pathlib import Path

import pytest

# Make project root importable when tests run from any cwd.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def block_fmp(monkeypatch):
    """Block any live FMP HTTP. Tests that need data should override get explicitly."""
    import fmp_client

    def _boom(*_args, **_kwargs):
        pytest.fail("Live FMP call attempted in tests")

    monkeypatch.setattr(fmp_client, "get", _boom)


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """Run with cwd at tmp_path so the relative cache/ and data/ paths land here."""
    (tmp_path / "data").mkdir()
    (tmp_path / "cache").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path
