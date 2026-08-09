"""Pytest fixtures for the timing-notion-sync module.

The production script is a single file `timing-notion-sync.py` with a hyphen
in its name and module-level side effects on import (it reads env vars and may
create a log dir). To test it we load it through importlib with a controlled
environment and expose its namespace as the `tns` fixture.

All fixtures set a fake but non-empty set of required env vars so import does
not trigger the error path.
"""

import importlib.util
import os
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "timing-notion-sync.py"


@pytest.fixture(scope="session")
def tns():
    """Load the timing-notion-sync module via importlib and return it."""
    os.environ.setdefault("TIMING_API_TOKEN", "test_timing_token")
    os.environ.setdefault("NOTION_API_TOKEN", "test_notion_token")
    os.environ.setdefault("NOTION_DATABASE_ID", "test_database_id")
    # Keep the heavy optional modes off for unit tests unless a test asks.
    os.environ.setdefault("SYNC_ENTRIES", "false")
    os.environ.setdefault("SYNC_SCREENTIME", "false")

    spec = importlib.util.spec_from_file_location("tns_mod", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module