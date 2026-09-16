"""Integration tests against the real App Store Connect API.

Skipped by default (see addopts in pyproject.toml). Run with:

    APP_STORE_CONNECT_KEY_ID=... APP_STORE_CONNECT_ISSUER_ID=... \
    APP_STORE_CONNECT_PRIVATE_KEY_PATH=... pytest -m integration

They only read data and use one lightweight request per behavior under test.
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("APP_STORE_CONNECT_KEY_ID"),
        reason="needs APP_STORE_CONNECT_KEY_ID and a private key",
    ),
]

from app_store_connect_mcp import server  # noqa: E402


def _tool(name):
    tool = getattr(server, name)
    return getattr(tool, "fn", tool)


@pytest.fixture(scope="module")
def app_ids():
    apps = _tool("list_apps")(limit=10).get("data", [])
    if not apps:
        pytest.skip("credentials see no App Store Connect apps")
    return [app["id"] for app in apps]


def test_apps_have_bundle_ids(app_ids):
    apps = _tool("list_apps")(limit=10)["data"]
    assert all(app.get("bundleId") for app in apps)


def test_report_requests_are_listable(app_ids):
    result = _tool("list_report_requests")(app_ids[0])
    assert isinstance(result["data"], list)


def test_reports_have_known_categories(app_ids):
    for app_id in app_ids:
        requests = _tool("list_report_requests")(app_id, access_type="ONGOING")["data"]
        if not requests:
            continue
        reports = _tool("list_reports")(str(requests[0]["id"]), limit=5)["data"]
        if not reports:
            continue
        assert all(report["category"] in server.REPORT_CATEGORIES for report in reports)
        return
    pytest.skip("no accessible app has an ongoing analytics report request yet")


def test_customer_reviews_respect_rating_filter(app_ids):
    reviews = _tool("list_customer_reviews")(app_ids[0], rating=[5], limit=3)["data"]
    assert all(review["rating"] == 5 for review in reviews)
