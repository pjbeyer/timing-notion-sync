"""Tests for the network-backed functions, using mocked requests.

No live API calls are made. We patch the `requests` module attribute on the
loaded module (tns.requests) so the module's own function calls hit fakes.
"""

from unittest import mock


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.text = str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests.exceptions import HTTPError

            raise HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._json


def _install_requests(tns, fn=None):
    """Replace tns.requests with the fake, optionally wrapping fn."""
    requests_mod = mock.MagicMock()

    def _wrap(name):
        def inner(*a, **k):
            return fn(*a, **k)

        return inner

    def get(*a, **k):
        return fn("get", *a, **k)

    def post(*a, **k):
        return fn("post", *a, **k)

    def patch(*a, **k):
        return fn("patch", *a, **k)

    def request(method, *a, **k):
        return fn(method, *a, **k)

    requests_mod.get = get
    requests_mod.post = post
    requests_mod.patch = patch
    requests_mod.request = request
    requests_mod.exceptions = __import__("requests").exceptions
    return requests_mod


def test_get_timing_entries(tns):
    captured = {}

    def fake(method, url, **kwargs):
        captured.update(url=url, params=kwargs.get("params"), headers=kwargs.get("headers"))
        return FakeResponse(
            {
                "data": [
                    {"duration": 60, "title": "t", "project": {"title": "p", "title_chain": ["p"]}}
                ]
            }
        )

    tns.requests = _install_requests(tns, fake)
    entries = tns.get_timing_entries("2026-08-09")

    assert len(entries) == 1
    assert captured["url"] == "https://web.timingapp.com/api/v1/time-entries"
    assert "start_date_min" in captured["params"]
    assert captured["headers"]["Authorization"] == "Bearer test_timing_token"


def test_find_notion_page(tns):
    initial = {"results": [{"id": "page-123"}]}
    tns.requests = _install_requests(tns, lambda m, *a, **k: FakeResponse(initial))
    assert tns.find_notion_page("2026-08-09", "Work > X") == "page-123"

    # No matches -> None
    tns.requests = _install_requests(tns, lambda m, *a, **k: FakeResponse({"results": []}))
    assert tns.find_notion_page("2026-08-09", "Nope") is None


def test_update_or_create_notion_page_update(tns):
    """Existing page -> PATCH to the page URL, token used."""
    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse({"id": "page-known"})

    tns.requests = _install_requests(tns, fake)
    result = tns.update_or_create_notion_page(
        page_id="page-known",
        date="2026-08-09",
        duration_seconds=3600,
        project="Work > X",
    )
    assert result == "page-known"
    assert calls[0][0] == "PATCH"
    assert "pages/page-known" in calls[0][1]


def test_update_or_create_notion_page_create(tns):
    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse({"id": "new-page"} if method == "POST" else {"id": "x"})

    tns.requests = _install_requests(tns, fake)
    result = tns.update_or_create_notion_page(
        page_id=None,
        date="2026-08-09",
        duration_seconds=1800,
        project="Meetings",
    )
    assert result == "new-page"
    assert calls[0][0] == "POST"
    assert "/v1/pages" in calls[0][1]
    # create payload includes the database id
    assert tns.NOTION_DATABASE_ID == "test_database_id"


def test_validation_error_falls_back_to_basic(tns):
    """When enhanced properties are rejected with a validation error, the
    fallback path should set the basic properties successfully."""
    calls = []

    def side(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        # First call = enhanced create -> returns a 400 validation_error
        # response whose raise_for_status() throws. Second call = the basic
        # fallback -> succeeds.
        if len(calls) == 1:
            return FakeResponse({"code": "validation_error"}, status_code=400)
        return FakeResponse({"id": "basic-page"})

    tns.requests = mock.MagicMock()
    # The module matches on requests.exceptions.RequestException; this must be
    # the REAL exceptions module so the raised HTTPError is caught.
    import requests as real_requests

    tns.requests.exceptions = real_requests.exceptions
    tns.requests.request = side
    tns.requests.post = side
    tns.requests.patch = side

    result = tns.update_or_create_notion_page(
        page_id=None,
        date="2026-08-09",
        duration_seconds=3600,
        project="Work > X",
        entry_count=5,
        top_entries=["A"],
    )
    # fallback ran and created the basic page
    assert result == "basic-page"
    # two calls: the enhanced create, then the basic fallback create
    assert len(calls) == 2