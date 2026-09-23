import gzip
import os
import time

import pytest

from app_store_connect_mcp import api, auth, server


def _tool(name):
    tool = getattr(server, name)
    return getattr(tool, "fn", tool)


@pytest.fixture(autouse=True)
def isolate_env_files(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.ENV_FILE_ENV, str(tmp_path / "absent.env"))
    auth.reset_cache()
    yield
    auth.reset_cache()


def _page(*items):
    return {"data": list(items), "links": {}}


def test_list_apps_maps_attributes(monkeypatch):
    calls = {}

    def fake_get(path, params=None):
        calls["path"], calls["params"] = path, params
        return {
            "data": [
                {"id": "123", "type": "apps", "attributes": {"name": "App", "bundleId": "com.e.a"}}
            ],
            "links": {"next": "https://api.appstoreconnect.apple.com/v1/apps?cursor=ABC&limit=50"},
        }

    monkeypatch.setattr(api, "get", fake_get)
    result = _tool("list_apps")(bundle_id="com.e.a")
    assert calls["path"] == "v1/apps"
    assert calls["params"]["filter[bundleId]"] == "com.e.a"
    assert result["data"] == [
        {"id": "123", "name": "App", "bundleId": "com.e.a", "sku": None, "primaryLocale": None}
    ]
    assert result["cursor"] == "ABC"


def test_create_report_request_builds_body(monkeypatch):
    calls = {}

    def fake_post(path, body):
        calls["path"], calls["body"] = path, body
        return {"data": {"id": "req-1", "attributes": {"accessType": "ONGOING"}}}

    monkeypatch.setattr(api, "post", fake_post)
    result = _tool("create_report_request")("123")
    assert calls["path"] == "v1/analyticsReportRequests"
    assert calls["body"]["data"]["attributes"] == {"accessType": "ONGOING"}
    assert calls["body"]["data"]["relationships"]["app"]["data"]["id"] == "123"
    assert result["id"] == "req-1"


def test_rejects_invalid_enums_and_ids():
    with pytest.raises(ValueError, match="access_type"):
        _tool("create_report_request")("123", "WEEKLY")
    with pytest.raises(ValueError, match="granularity"):
        _tool("list_report_instances")("r-1", granularity="HOURLY")
    with pytest.raises(ValueError, match="app_id"):
        _tool("list_report_requests")("../secrets")
    with pytest.raises(ValueError, match="category"):
        _tool("list_reports")("req-1", category="REVENUE")


def test_processing_date_must_be_iso(monkeypatch):
    monkeypatch.setattr(api, "get", lambda path, params=None: _page())
    with pytest.raises(api.AppStoreConnectApiError, match="YYYY-MM-DD"):
        _tool("list_report_instances")("r-1", processing_date="01/08/2026")


def test_fetch_analytics_report_walks_the_chain(monkeypatch):
    responses = {
        "v1/apps/123/analyticsReportRequests": _page(
            {
                "id": "req-1",
                "attributes": {"accessType": "ONGOING", "stoppedDueToInactivity": False},
            }
        ),
        "v1/analyticsReportRequests/req-1/reports": _page(
            {
                "id": "rep-1",
                "attributes": {"name": "App Sessions Standard", "category": "APP_USAGE"},
            }
        ),
        "v1/analyticsReports/rep-1/instances": _page(
            {
                "id": "inst-old",
                "attributes": {"granularity": "DAILY", "processingDate": "2026-09-01"},
            },
            {
                "id": "inst-new",
                "attributes": {"granularity": "DAILY", "processingDate": "2026-09-10"},
            },
        ),
        "v1/analyticsReportInstances/inst-new/segments": _page(
            {"id": "seg-1", "attributes": {"url": "https://example.com/seg", "sizeInBytes": 20}}
        ),
    }
    monkeypatch.setattr(api, "get", lambda path, params=None: responses[path])
    monkeypatch.setattr(
        api, "download", lambda url, max_bytes: gzip.compress(b"Date\tSessions\n2026-09-09\t7\n")
    )

    result = _tool("fetch_analytics_report")("123", "App Sessions Standard")
    assert result["processingDate"] == "2026-09-10"
    assert result["reportId"] == "rep-1"
    assert result["rows"] == [{"Date": "2026-09-09", "Sessions": "7"}]
    assert result["truncated"] is False


def test_fetch_analytics_report_without_request_explains_how_to_create(monkeypatch):
    monkeypatch.setattr(api, "get", lambda path, params=None: _page())
    with pytest.raises(ValueError, match="create_report_request"):
        _tool("fetch_analytics_report")("123", "App Sessions Standard")


def test_fetch_analytics_report_lists_available_names(monkeypatch):
    responses = {
        "v1/apps/123/analyticsReportRequests": _page(
            {"id": "req-1", "attributes": {"accessType": "ONGOING"}}
        ),
    }

    def fake_get(path, params=None):
        if path == "v1/analyticsReportRequests/req-1/reports":
            if params and params.get("filter[name]"):
                return _page()
            return _page({"id": "rep-1", "attributes": {"name": "App Crashes Expanded"}})
        return responses[path]

    monkeypatch.setattr(api, "get", fake_get)
    with pytest.raises(ValueError, match="App Crashes Expanded"):
        _tool("fetch_analytics_report")("123", "Nope")


def test_sales_report_validates_date_per_frequency(monkeypatch):
    calls = {}

    def fake_get_bytes(path, params=None):
        calls["path"], calls["params"] = path, params
        return gzip.compress(b"Provider\tUnits\nAPPLE\t3\n")

    monkeypatch.setattr(api, "get_bytes", fake_get_bytes)
    monkeypatch.setenv(auth.VENDOR_NUMBER_ENV, "12345678")

    result = _tool("download_sales_report")("SALES", "SUMMARY", "MONTHLY", "2026-08")
    assert calls["path"] == "v1/salesReports"
    assert calls["params"]["filter[vendorNumber]"] == "12345678"
    assert result["rows"] == [{"Provider": "APPLE", "Units": "3"}]

    with pytest.raises(api.AppStoreConnectApiError, match="YYYY-MM"):
        _tool("download_sales_report")("SALES", "SUMMARY", "MONTHLY", "2026-08-01")
    with pytest.raises(ValueError, match="frequency"):
        _tool("download_sales_report")("SALES", "SUMMARY", "HOURLY", "2026-08")


def test_sales_report_requires_vendor_number(monkeypatch):
    monkeypatch.delenv(auth.VENDOR_NUMBER_ENV, raising=False)
    monkeypatch.setattr(api, "get_bytes", lambda path, params=None: b"")
    with pytest.raises(auth.CredentialsError, match=auth.VENDOR_NUMBER_ENV):
        _tool("download_sales_report")("SALES", "SUMMARY", "DAILY", "2026-08-01")


def test_finance_report_uses_fiscal_month(monkeypatch):
    calls = {}
    monkeypatch.setenv(auth.VENDOR_NUMBER_ENV, "12345678")
    monkeypatch.setattr(
        api,
        "get_bytes",
        lambda path, params=None: calls.update(params=params) or b"Region\tEarned\nBR\t10\n",
    )
    result = _tool("download_finance_report")("2026-08")
    assert calls["params"]["filter[regionCode]"] == "ZZ"
    assert result["rows"] == [{"Region": "BR", "Earned": "10"}]
    with pytest.raises(api.AppStoreConnectApiError, match="YYYY-MM"):
        _tool("download_finance_report")("2026")


def test_customer_reviews_encodes_filters(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        api, "get", lambda path, params=None: calls.update(path=path, params=params) or _page()
    )
    _tool("list_customer_reviews")("123", rating=[1, 2], territory=["bra"], sort="rating")
    assert calls["path"] == "v1/apps/123/customerReviews"
    assert calls["params"]["filter[rating]"] == [1, 2]
    assert calls["params"]["filter[territory]"] == ["BRA"]
    assert calls["params"]["sort"] == "rating"


def test_perf_power_metrics_validates_metric_type(monkeypatch):
    monkeypatch.setattr(api, "get", lambda path, params=None: {"productData": []})
    assert _tool("get_perf_power_metrics")("123", metric_type="launch") == {"productData": []}
    with pytest.raises(ValueError, match="metric_type"):
        _tool("get_perf_power_metrics")("123", metric_type="CPU")


def test_encode_joins_lists_and_drops_none():
    encoded = api._encode({"a": [1, 2], "b": None, "c": True, "d": "x", "e": []})
    assert encoded == {"a": "1,2", "c": "true", "d": "x"}


def test_parse_table_detects_delimiter_and_truncates():
    tsv = api.parse_table(b"a\tb\n1\t2\n3\t4\n", max_rows=1)
    assert tsv["columns"] == ["a", "b"]
    assert tsv["rows"] == [{"a": "1", "b": "2"}]
    assert tsv["truncated"] is True
    csv_result = api.parse_table(b"a,b\n1,2\n", max_rows=10)
    assert csv_result["rows"] == [{"a": "1", "b": "2"}]


def test_decompress_rejects_oversized_payload():
    with pytest.raises(api.AppStoreConnectApiError, match="max_bytes"):
        api.decompress(gzip.compress(b"x" * 5000), max_bytes=1024)
    assert api.decompress(b"plain", max_bytes=1024) == b"plain"


def test_cursor_of_handles_missing_link():
    assert api.cursor_of({"data": []}) is None
    assert api.cursor_of({"links": {"next": "https://x/y?limit=1"}}) is None


def test_download_rejects_non_https_url():
    with pytest.raises(api.AppStoreConnectApiError, match="HTTPS"):
        api.download("file:///etc/passwd", 1024)


def test_error_message_uses_apple_error_payload():
    class FakeResponse:
        status_code = 409
        text = "raw"

        def json(self):
            return {"errors": [{"title": "Conflict", "detail": "Report request exists"}]}

    with pytest.raises(api.AppStoreConnectApiError, match="Report request exists"):
        api._raise_for_error(FakeResponse())


def test_token_is_signed_and_cached(monkeypatch, tmp_path):
    key = tmp_path / "AuthKey_TEST123456.p8"
    key.write_text(_generate_p8())
    monkeypatch.setenv(auth.KEY_ID_ENV, "TEST123456")
    monkeypatch.setenv(auth.ISSUER_ID_ENV, "57246542-96fe-1a63-e053-0824d011072a")
    monkeypatch.setenv(auth.PRIVATE_KEY_PATH_ENV, str(key))
    auth.reset_cache()

    token = auth.get_token()
    assert auth.get_token() is token

    import jwt

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False}, audience=auth.AUDIENCE)
    assert header == {"alg": "ES256", "kid": "TEST123456", "typ": "JWT"}
    assert claims["iss"] == "57246542-96fe-1a63-e053-0824d011072a"
    assert "sub" not in claims
    assert 0 < claims["exp"] - time.time() <= auth.TOKEN_LIFETIME
    auth.reset_cache()


def test_individual_key_uses_sub_instead_of_issuer(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.KEY_ID_ENV, "TEST123456")
    monkeypatch.delenv(auth.ISSUER_ID_ENV, raising=False)
    monkeypatch.setenv(auth.PRIVATE_KEY_ENV, _generate_p8())
    auth.reset_cache()

    import jwt

    claims = jwt.decode(
        auth.get_token(), options={"verify_signature": False}, audience=auth.AUDIENCE
    )
    assert claims["sub"] == "user"
    assert "iss" not in claims
    auth.reset_cache()


def test_missing_credentials_are_reported_clearly(monkeypatch):
    monkeypatch.delenv(auth.KEY_ID_ENV, raising=False)
    auth.reset_cache()
    with pytest.raises(auth.CredentialsError, match=auth.KEY_ID_ENV):
        auth.get_token()

    monkeypatch.setenv(auth.KEY_ID_ENV, "TEST123456")
    monkeypatch.delenv(auth.PRIVATE_KEY_ENV, raising=False)
    monkeypatch.delenv(auth.PRIVATE_KEY_PATH_ENV, raising=False)
    with pytest.raises(auth.CredentialsError, match=auth.PRIVATE_KEY_PATH_ENV):
        auth.get_token()
    auth.reset_cache()


def test_env_file_fills_missing_variables(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# credenciais\n"
        "export APP_STORE_CONNECT_KEY_ID=FROMFILE12\n"
        'APP_STORE_CONNECT_VENDOR_NUMBER="87654321"\n'
        "\n"
    )
    monkeypatch.setenv(auth.ENV_FILE_ENV, str(env_file))
    monkeypatch.delenv(auth.KEY_ID_ENV, raising=False)
    monkeypatch.delenv(auth.VENDOR_NUMBER_ENV, raising=False)
    auth.reset_cache()

    assert auth.get_vendor_number() == "87654321"
    assert os.environ[auth.KEY_ID_ENV] == "FROMFILE12"


def test_env_file_with_bom_keeps_first_variable(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xef\xbb\xbfAPP_STORE_CONNECT_VENDOR_NUMBER=87654321\r\n")
    monkeypatch.setenv(auth.ENV_FILE_ENV, str(env_file))
    monkeypatch.delenv(auth.VENDOR_NUMBER_ENV, raising=False)
    auth.reset_cache()

    assert auth.get_vendor_number() == "87654321"


def test_real_environment_wins_over_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_STORE_CONNECT_VENDOR_NUMBER=11111111\n")
    monkeypatch.setenv(auth.ENV_FILE_ENV, str(env_file))
    monkeypatch.setenv(auth.VENDOR_NUMBER_ENV, "22222222")
    auth.reset_cache()

    assert auth.get_vendor_number() == "22222222"


def test_missing_env_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.ENV_FILE_ENV, str(tmp_path / "nope.env"))
    auth.reset_cache()
    auth.load_env_files()


def _generate_p8() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
