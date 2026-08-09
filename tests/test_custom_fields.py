"""Tests for custom_fields propagation (SYNC_CUSTOM_FIELDS)."""

import importlib.util
import os

import pytest

from conftest import MODULE_PATH, tns


def test_safe_custom_fields_returns_string_pairs(tns):
    assert tns._safe_custom_fields({"dayflow_flexmbp": "Reviewed PR"}) == {
        "dayflow_flexmbp": "Reviewed PR"
    }
    # non-dict / missing -> empty
    assert tns._safe_custom_fields(None) == {}
    assert tns._safe_custom_fields("not-a-dict") == {}
    assert tns._safe_custom_fields([]) == {}
    # non-string values are dropped
    assert tns._safe_custom_fields({"a": "x", "b": 5, "c": None}) == {"a": "x"}


def test_custom_fields_summary(tns):
    cf = {"dayflow_flexmbp": "Reviewed PR", "source": "dayflow"}
    out = tns._custom_fields_summary(cf)
    assert "dayflow_flexmbp: Reviewed PR" in out
    assert "source: dayflow" in out
    # empty -> empty
    assert tns._custom_fields_summary({}) == ""
    # truncation at limit
    big = {"k": "x" * 100}
    truncated = tns._custom_fields_summary(big, limit=20)
    assert len(truncated) <= 20
    assert truncated.endswith("...")


def test_process_timing_entries_captures_custom_fields(tns):
    entries = [
        {
            "duration": 600,
            "title": "Enriched work",
            "project": {"title": "P", "title_chain": ["P"]},
            "custom_fields": {"dayflow_flexmbp": "Summary text"},
        },
        {
            "duration": 300,
            "title": "No fields",
            "project": {"title": "Q", "title_chain": ["Q"]},
            # custom_fields missing entirely
        },
    ]
    result = tns.process_timing_entries(entries)

    by_title = {e["title"]: e for e in result["entry_details"]}
    assert by_title["Enriched work"]["custom_fields"] == {"dayflow_flexmbp": "Summary text"}
    # missing custom_fields -> empty dict (not an error)
    assert by_title["No fields"]["custom_fields"] == {}


def _load_with_custom_fields(enabled):
    os.environ["TIMING_API_TOKEN"] = "t"
    os.environ["NOTION_API_TOKEN"] = "n"
    os.environ["NOTION_DATABASE_ID"] = "default_db"
    os.environ["PROJECT_DB_MAP"] = "{}"
    os.environ["WORKSPACES"] = "{}"
    os.environ["WORKSPACE_MAP"] = "{}"
    os.environ["SYNC_CUSTOM_FIELDS"] = "true" if enabled else "false"
    spec = importlib.util.spec_from_file_location("tns_cf", MODULE_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sync_custom_fields_flag(tns):
    # default off
    assert tns.SYNC_CUSTOM_FIELDS is False


def test_sync_custom_fields_enabled():
    m = _load_with_custom_fields(True)
    assert m.SYNC_CUSTOM_FIELDS is True


def test_sync_custom_fields_renders_block():
    """When SYNC_CUSTOM_FIELDS is on, update_page_content_with_entries adds a
    green sub-paragraph with the custom_fields summary."""
    m = _load_with_custom_fields(True)

    # Build the children list by invoking the function with a mocked requests.
    import requests as real_requests

    calls = []

    def patch(url, **kwargs):
        calls.append(kwargs.get("json", {}).get("children", []))
        return type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {},
                "status_code": 200,
            },
        )()

    m.requests = type("M", (), {"exceptions": real_requests.exceptions})()
    m.requests.patch = patch

    entries = [
        {
            "title": "Enriched",
            "duration_seconds": 600,
            "start_time": "",
            "notes": "",
            "custom_fields": {"dayflow_flexmbp": "Reviewed PR"},
        }
    ]
    ok = m.update_page_content_with_entries("page-1", entries, token="tok")

    assert ok is True
    assert len(calls) == 1
    children = calls[0]
    bullets = [
        c["bulleted_list_item"]
        for c in children
        if c.get("type") == "bulleted_list_item"
    ]
    assert len(bullets) == 1
    bullet = bullets[0]
    sub_blocks = bullet.get("children", [])
    # one custom-fields green paragraph
    assert len(sub_blocks) == 1
    assert sub_blocks[0]["type"] == "paragraph"
    assert sub_blocks[0]["paragraph"]["rich_text"][0]["annotations"]["color"] == "green"
    assert "Reviewed PR" in sub_blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]