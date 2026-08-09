"""Tests for pure helper/parsing functions in timing-notion-sync.py.

These cover behaviour that does not require network access: time formatting,
duration math, and the JSON/entry-structure parsing that drives the Notion
upsert. Network-backed functions (get_timing_entries, Notion query/update) are
exercised via mocked unit tests rather than live calls.
"""

import pytest


def test_seconds_to_duration_string(tns):
    assert tns.seconds_to_duration_string(0) == "0:00:00"
    assert tns.seconds_to_duration_string(59) == "0:00:59"
    assert tns.seconds_to_duration_string(60) == "0:01:00"
    assert tns.seconds_to_duration_string(3600) == "1:00:00"
    assert tns.seconds_to_duration_string(3661) == "1:01:01"
    assert tns.seconds_to_duration_string(90061) == "25:01:01"


def test_local_timezone_offset_shape(tns):
    """Offset must look like +HH:MM or -HH:MM."""
    offset = tns.get_local_timezone_offset()
    assert len(offset) == 6
    assert offset[0] in ("+", "-")
    assert offset[3] == ":"
    assert offset[1:3].isdigit()
    assert offset[4:6].isdigit()


def test_process_timing_entries(tns):
    entries = [
        {
            "duration": 1800,
            "title": "Email triage",
            "notes": "Inbox zero",
            "start_date": "2026-08-09T09:00:00-04:00",
            "end_date": "2026-08-09T09:30:00-04:00",
            "is_running": False,
            "project": {
                "title": "Project X",
                "title_chain": ["Work", "Client A", "Project X"],
            },
        },
        {
            "duration": 3600,
            "title": "Standup",
            "notes": "",
            "start_date": "2026-08-09T10:00:00-04:00",
            "end_date": "2026-08-09T11:00:00-04:00",
            "is_running": False,
            "project": {
                "title": "Meetings",
                "title_chain": ["Work", "Meetings"],
            },
        },
        {
            "duration": 0,  # zero-duration entries are skipped
            "title": "No time",
            "project": None,
        },
    ]

    result = tns.process_timing_entries(entries)

    assert result["total_seconds"] == 5400
    assert len(result["entry_details"]) == 2
    assert len(result["project_totals"]) == 2

    # Full hierarchy used as the grouping key + project name
    assert "Work > Client A > Project X" in result["project_totals"]
    proj = result["project_totals"]["Work > Client A > Project X"]
    assert proj["project_name"] == "Project X"
    assert proj["total_duration"] == 1800
    assert proj["entry_count"] == 1

    # Entry detail fields
    detail = result["entry_details"][0]
    assert detail["project_path"] == "Work > Client A > Project X"
    assert detail["project_name"] == "Project X"
    assert detail["duration_hours"] == pytest.approx(0.5)


def test_process_timing_entries_no_project(tns):
    """Entries without a project go to Uncategorized."""
    result = tns.process_timing_entries([{"duration": 300, "title": "x", "project": None}])
    assert result["project_totals"]["Uncategorized"]["total_duration"] == 300


def test_bundle_to_app_name(tns):
    assert tns._bundle_to_app_name("com.apple.Safari") == "Safari"
    assert tns._bundle_to_app_name("com.microsoft.VSCode") == "VS Code"
    assert tns._bundle_to_app_name("") == "Unknown"
    assert tns._bundle_to_app_name(None) == "Unknown"
    # Unknown bundle falls back to a humanised title
    assert tns._bundle_to_app_name("com.example.SomeApp") == "Someapp"