import os

import pytest


@pytest.fixture(autouse=True)
def _clean_ducklake_env(monkeypatch):
    """Keep the developer's own DUCKLAKE_* variables out of the settings under test."""
    for name in list(os.environ):
        if name.startswith("DUCKLAKE_"):
            monkeypatch.delenv(name)
