"""Tests for multi-workspace routing (WORKSPACES / WORKSPACE_MAP).

Verifies the fail-closed structural routing: a project folder's workspace is
fixed by config, so family projects can never be written to a work workspace
and vice versa.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from conftest import MODULE_PATH

WORKSPACES_CFG = (
    '{"gsd": {"token_env": "NOTION_API_TOKEN", '
    '"databases": {"Family": "family_db"}}, '
    '"flex": {"token_env": "NOTION_API_TOKEN_FLEX", '
    '"databases": {"Work": "work_db", "Consulting": "consult_db"}}}'
)
MAP_CFG = '{"Family": "gsd", "Work": "flex", "Consulting": "flex"}'


def _load(workspaces_override=None, map_override=None, extra_env=None):
    os.environ["PROJECT_DB_MAP"] = "{}"
    os.environ["WORKSPACES"] = workspaces_override if workspaces_override is not None else WORKSPACES_CFG
    os.environ["WORKSPACE_MAP"] = map_override if map_override is not None else MAP_CFG
    os.environ["NOTION_API_TOKEN"] = "default_token"
    os.environ["NOTION_API_TOKEN_FLEX"] = "flex_token"
    os.environ["NOTION_DATABASE_ID"] = "default_db"
    os.environ["TIMING_API_TOKEN"] = "t"
    if extra_env:
        os.environ.update(extra_env)
    spec = importlib.util.spec_from_file_location("tns_ws", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws():
    return _load()


def test_routes_to_workspace_token_and_db(ws):
    target = ws.resolve_workspace("Family > Groceries")
    assert target["name"] == "gsd"
    assert target["token"] == "default_token"  # gsd uses NOTION_API_TOKEN
    assert target["database_id"] == "family_db"

    target = ws.resolve_workspace("Work > Client A")
    assert target["name"] == "flex"
    assert target["token"] == "flex_token"  # flex uses NOTION_API_TOKEN_FLEX
    assert target["database_id"] == "work_db"

    target = ws.resolve_workspace("Consulting > Engagement")
    assert target["name"] == "flex"
    assert target["token"] == "flex_token"
    assert target["database_id"] == "consult_db"


def test_unmapped_root_uses_default(ws):
    # A root not in WORKSPACE_MAP -> default workspace/token/db
    target = ws.resolve_workspace("Meetings > Standup")
    assert target["name"] == "default"
    assert target["token"] == "default_token"
    assert target["database_id"] == "default_db"


def test_fail_closed_structural_routing(ws):
    """Routing is a pure function of config: family root maps ONLY to gsd."""
    # Family root never resolves to flex
    assert ws.resolve_workspace("Family > Anything")["name"] == "gsd"
    assert ws.resolve_workspace("Family > Anything")["database_id"] == "family_db"
    # The flex workspace token/db are unreachable for family projects
    t = ws.resolve_workspace("Family > Groceries")
    assert t["token"] != "flex_token"
    assert t["database_id"] != "work_db"


def test_workspace_token_used_in_notion_calls(ws):
    """The routed workspace token is sent to Notion for that project."""
    import requests as real_requests

    def _resp(method, url):
        j = {"results": [{"id": "p"}]} if method == "POST" else {"id": "p"}
        return type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: j,
                "status_code": 200,
            },
        )()

    # find_notion_page -> requests.post(url, headers=...)
    seen = {}
    def fake_post(url, **kwargs):
        seen["auth"] = kwargs.get("headers", {}).get("Authorization")
        seen["url"] = url
        return _resp("POST", url)

    ws.requests = type("M", (), {"exceptions": real_requests.exceptions})()
    ws.requests.post = fake_post
    ws.find_notion_page("2026-08-09", "Work > Client A", database_id="work_db", token="flex_token")
    assert seen["url"] == "https://api.notion.com/v1/databases/work_db/query"
    assert seen["auth"] == "Bearer flex_token"

    # update/create -> requests.request(method, url, headers=...)
    seen.clear()
    def fake_request(method, url, **kwargs):
        seen["auth"] = kwargs.get("headers", {}).get("Authorization")
        seen["method"] = method
        seen["parent"] = kwargs.get("json", {}).get("parent", {}).get("database_id")
        return _resp(method, url)

    ws.requests.request = fake_request
    ws.update_or_create_notion_page(
        page_id=None,
        date="2026-08-09",
        duration_seconds=1800,
        project="Family > Groceries",
        database_id="family_db",
        token="default_token",
    )
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer default_token"
    assert seen["parent"] == "family_db"


def test_default_workspace_when_no_config():
    """No WORKSPACES/WORKSPACE_MAP -> default workspace everywhere."""
    m = _load(workspaces_override="{}", map_override="{}")
    t = m.resolve_workspace("Work > Client A")
    assert t == {"token": "default_token", "database_id": "default_db", "name": "default"}