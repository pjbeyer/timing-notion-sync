"""Tests for multi-database routing (PROJECT_DB_MAP)."""

import importlib.util
import os
from pathlib import Path

import pytest

from conftest import MODULE_PATH


def _load_with_db_map(db_map_env):
    os.environ["PROJECT_DB_MAP"] = db_map_env
    os.environ["TIMING_API_TOKEN"] = "t"
    os.environ["NOTION_API_TOKEN"] = "n"
    os.environ["NOTION_DATABASE_ID"] = "default_db"
    spec = importlib.util.spec_from_file_location("tns_multidb", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def multidb():
    return _load_with_db_map(
        '{"Work": "work_db", "Family": "family_db", "Consulting": "consulting_db"}'
    )


def test_resolve_database_id_top_level_folder(multidb):
    assert multidb.resolve_database_id("Work > Client A > Project X") == "work_db"
    assert multidb.resolve_database_id("Family > Groceries") == "family_db"
    assert multidb.resolve_database_id("Consulting > Engagement") == "consulting_db"


def test_resolve_database_id_fallback(multidb):
    # Unmatched root falls back to the default
    assert multidb.resolve_database_id("Meetings") == "default_db"
    assert multidb.resolve_database_id("Uncategorized") == "default_db"
    assert multidb.resolve_database_id("") == "default_db"


def test_resolve_database_id_leaf_only(multidb):
    # A single-segment path that IS a key uses that key
    assert multidb.resolve_database_id("Work") == "work_db"


def test_db_map_parsing(multidb):
    assert multidb.PROJECT_DB_MAP == {
        "Work": "work_db",
        "Family": "family_db",
        "Consulting": "consulting_db",
    }


def test_invalid_db_map_falls_back(multidb):
    # Load with invalid JSON -> empty map -> all to default
    os.environ["PROJECT_DB_MAP"] = "not-json"
    module = _load_with_db_map("not-json")
    assert module.PROJECT_DB_MAP == {}
    assert module.resolve_database_id("Work > X") == "default_db"


def test_none_db_map_is_empty():
    module = _load_with_db_map("")
    assert module.PROJECT_DB_MAP == {}
    assert module.resolve_database_id("Work > X") == "default_db"


def test_db_id_threaded_through_find_notion_page(multidb):
    """find_notion_page uses the routed database in the query URL."""
    import requests as real_requests

    calls = []

    def fake(url, **kwargs):
        calls.append(url)
        return type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"results": [{"id": "found"}]},
                "status_code": 200,
            },
        )()

    multidb.requests = type("M", (), {"exceptions": real_requests.exceptions})()
    multidb.requests.post = fake

    pid = multidb.find_notion_page(
        "2026-08-09", "Work > Client A", database_id="work_db"
    )
    assert pid == "found"
    assert "/databases/work_db/query" in calls[0]


def test_db_id_threaded_through_update_create(multidb):
    """Create uses the routed database id in the parent payload."""
    import requests as real_requests

    captured = {}

    def fake(method, url, **kwargs):
        captured["json"] = kwargs.get("json")
        captured["method"] = method
        return type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"id": "new-page"},
                "status_code": 200,
            },
        )()

    multidb.requests = type("M", (), {"exceptions": real_requests.exceptions})()
    multidb.requests.request = fake

    pid = multidb.update_or_create_notion_page(
        page_id=None,
        date="2026-08-09",
        duration_seconds=3600,
        project="Work > Client A",
        database_id="work_db",
    )
    assert pid == "new-page"
    assert captured["method"] == "POST"
    assert captured["json"]["parent"]["database_id"] == "work_db"