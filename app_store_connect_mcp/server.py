"""FastMCP server exposing App Store Connect analytics and report data.

Data sources:
- Analytics Reports API (app usage, App Store engagement, commerce, framework
  usage and performance reports as gzipped TSV):
  https://developer.apple.com/documentation/appstoreconnectapi/analytics
- Sales and Trends reports (sales, installs, subscriptions, subscribers...):
  https://developer.apple.com/documentation/appstoreconnectapi/download-sales-and-trends-reports
- Finance reports, customer reviews and power/performance metrics.
"""

from __future__ import annotations

import argparse
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import api
from .auth import get_vendor_number

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)

mcp = FastMCP(
    name="app-store-connect",
    instructions=(
        "Analytics and report data from App Store Connect. Use list_apps to "
        "discover app IDs, then list_report_requests (and, once per app, "
        "create_report_request) to enable the Analytics Reports API. "
        "fetch_analytics_report is the one-shot path from an app to parsed "
        "report rows; list_reports/list_report_instances/list_report_segments/"
        "download_report_instance expose each step. download_sales_report and "
        "download_finance_report cover Sales and Trends and Finance, "
        "list_customer_reviews the App Store reviews, and get_perf_power_metrics "
        "the Xcode power and performance metrics."
    ),
)

REPORT_CATEGORIES = {
    "APP_USAGE": "Sessions, active devices, installs and deletions, crashes.",
    "APP_STORE_ENGAGEMENT": "Impressions, product page views, downloads by source.",
    "COMMERCE": "Purchases, proceeds, subscription events and retention.",
    "FRAMEWORK_USAGE": "Usage of system frameworks and APIs by the app.",
    "PERFORMANCE": "Launch time, hangs, memory, disk and battery metrics.",
}

COMMON_REPORTS = {
    "APP_USAGE": [
        "App Sessions Standard",
        "App Sessions Detailed",
        "App Store Installation and Deletion Standard",
        "App Store Installation and Deletion Detailed",
        "App Crashes",
        "Platform App Installs",
    ],
    "APP_STORE_ENGAGEMENT": [
        "App Store Discovery and Engagement Standard",
        "App Store Discovery and Engagement Detailed",
        "App Store Web Preview Engagement Standard",
        "Retention Messaging",
    ],
    "COMMERCE": [
        "App Downloads Standard",
        "App Downloads Detailed",
        "App Store Purchases Standard",
        "App Store Subscription Event Report Standard",
        "App Store Subscription State Report Standard",
    ],
}

GRANULARITIES = ("DAILY", "WEEKLY", "MONTHLY")
ACCESS_TYPES = ("ONGOING", "ONE_TIME_SNAPSHOT")

SALES_REPORT_TYPES: list[dict[str, Any]] = [
    {"reportType": "SALES", "reportSubType": "SUMMARY",
     "frequency": ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"], "version": ["1_0"]},
    {"reportType": "INSTALLS", "reportSubType": "SUMMARY",
     "frequency": ["MONTHLY"], "version": ["1_2"]},
    {"reportType": "INSTALLS", "reportSubType": "DETAILED",
     "frequency": ["MONTHLY", "YEARLY"], "version": ["1_2", "1_1", "1_0"]},
    {"reportType": "INSTALLS", "reportSubType": "SUMMARY_TERRITORY",
     "frequency": ["YEARLY"], "version": ["1_0", "1_1"]},
    {"reportType": "INSTALLS", "reportSubType": "SUMMARY_INSTALL_TYPE",
     "frequency": ["YEARLY"], "version": ["1_0", "1_1"]},
    {"reportType": "INSTALLS", "reportSubType": "SUMMARY_CHANNEL",
     "frequency": ["YEARLY"], "version": ["1_0", "1_1"]},
    {"reportType": "SUBSCRIPTION", "reportSubType": "SUMMARY",
     "frequency": ["DAILY"], "version": ["1_3"]},
    {"reportType": "SUBSCRIPTION_EVENT", "reportSubType": "SUMMARY",
     "frequency": ["DAILY"], "version": ["1_3"]},
    {"reportType": "SUBSCRIBER", "reportSubType": "DETAILED",
     "frequency": ["DAILY"], "version": ["1_3"]},
    {"reportType": "SUBSCRIPTION_OFFER_CODE_REDEMPTION", "reportSubType": "SUMMARY",
     "frequency": ["DAILY"], "version": ["1_0"]},
    {"reportType": "WIN_BACK_ELIGIBILITY", "reportSubType": "SUMMARY",
     "frequency": ["DAILY"], "version": ["1_0"]},
    {"reportType": "PRE_ORDER", "reportSubType": "SUMMARY",
     "frequency": ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"], "version": ["1_0"]},
    {"reportType": "FIRST_ANNUAL", "reportSubType": "DETAILED",
     "frequency": ["DAILY"], "version": ["1_0"]},
    {"reportType": "FIRST_ANNUAL", "reportSubType": "SUMMARY",
     "frequency": ["YEARLY"], "version": ["1_0"]},
    {"reportType": "NEWSSTAND", "reportSubType": "DETAILED",
     "frequency": ["DAILY", "WEEKLY"], "version": ["1_0"]},
]

FREQUENCY_DATE_FORMAT = {
    "DAILY": "%Y-%m-%d",
    "WEEKLY": "%Y-%m-%d",
    "MONTHLY": "%Y-%m",
    "YEARLY": "%Y",
}

REVIEW_SORTS = {
    "-CREATEDDATE": "-createdDate",
    "CREATEDDATE": "createdDate",
    "RATING": "rating",
    "-RATING": "-rating",
}

PERF_METRIC_TYPES = (
    "DISK", "HANG", "BATTERY", "LAUNCH", "MEMORY", "ANIMATION", "TERMINATION", "STORAGE",
)


def _clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


def _resource_id(value: str, label: str) -> str:
    cleaned = str(value).strip()
    if not cleaned or "/" in cleaned or "?" in cleaned:
        raise ValueError(f"Invalid {label} {value!r}: expected an App Store Connect resource ID")
    return cleaned


def _one_of(value: str, allowed: tuple[str, ...], label: str) -> str:
    upper = str(value).upper()
    if upper not in allowed:
        raise ValueError(f"Invalid {label} {value!r}. Valid: {list(allowed)}")
    return upper


def _attributes(item: dict[str, Any], *names: str) -> dict[str, Any]:
    attributes = item.get("attributes") or {}
    picked = {name: attributes.get(name) for name in names}
    return {"id": item.get("id"), **picked}


def _page(payload: dict[str, Any], *names: str) -> dict[str, Any]:
    return {
        "data": [_attributes(item, *names) for item in payload.get("data", [])],
        "cursor": api.cursor_of(payload),
    }


@mcp.tool(annotations=READ_ONLY)
def list_apps(
    name: str | None = None,
    bundle_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List the apps the configured API key can access.

    Use this first to discover the numeric app IDs the other tools take.

    Args:
        name: Optional exact app name to filter by.
        bundle_id: Optional bundle ID to filter by, e.g. "com.example.app".
        limit: Apps per page (1-200).
        cursor: Pagination cursor returned by a previous call.
    """
    params: dict[str, Any] = {
        "limit": _clamp(limit, 1, 200),
        "fields[apps]": ["name", "bundleId", "sku", "primaryLocale"],
        "filter[name]": name,
        "filter[bundleId]": bundle_id,
        "cursor": cursor,
    }
    return _page(api.get("v1/apps", params), "name", "bundleId", "sku", "primaryLocale")


@mcp.tool(annotations=READ_ONLY)
def list_report_categories() -> dict[str, Any]:
    """Describe the Analytics Reports categories and how the API is structured.

    `commonReports` lists the names Apple ships for most apps; the full set
    depends on the app and changes over time, so confirm with list_reports.
    Standard reports are pre-aggregated; Detailed ones break the same data down
    by more dimensions and are much larger.
    """
    return {
        "categories": REPORT_CATEGORIES,
        "commonReports": COMMON_REPORTS,
        "granularities": list(GRANULARITIES),
        "accessTypes": {
            "ONGOING": "Generated daily from the request date onwards (current data).",
            "ONE_TIME_SNAPSHOT": "One-off dump of the available historical data.",
        },
        "flow": (
            "app -> report request (create_report_request, once per app and "
            "access type) -> reports (list_reports) -> instances per "
            "granularity and processing date (list_report_instances) -> "
            "segments with the gzipped TSV data (list_report_segments / "
            "download_report_instance). fetch_analytics_report does the whole "
            "chain in one call."
        ),
        "notes": (
            "A new ONGOING request only starts producing data the next day, and "
            "report instances expire, so download them soon after listing. "
            "Segment download URLs are valid for 5 minutes."
        ),
    }


@mcp.tool(annotations=READ_ONLY)
def list_report_requests(
    app_id: str,
    access_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List the analytics report requests that exist for an app.

    Args:
        app_id: Numeric app ID from list_apps.
        access_type: Optional "ONGOING" or "ONE_TIME_SNAPSHOT" filter.
        limit: Requests per page (1-200).
    """
    params: dict[str, Any] = {
        "limit": _clamp(limit, 1, 200),
        "fields[analyticsReportRequests]": ["accessType", "stoppedDueToInactivity"],
    }
    if access_type:
        params["filter[accessType]"] = _one_of(access_type, ACCESS_TYPES, "access_type")
    payload = api.get(f"v1/apps/{_resource_id(app_id, 'app_id')}/analyticsReportRequests", params)
    return _page(payload, "accessType", "stoppedDueToInactivity")


@mcp.tool(annotations=WRITE)
def create_report_request(app_id: str, access_type: str = "ONGOING") -> dict[str, Any]:
    """Enable analytics reports for an app by creating a report request.

    This is the only write operation in this server, and it is required once
    per app: without a request App Store Connect generates no reports. ONGOING
    requests start producing data the day after creation; ONE_TIME_SNAPSHOT
    returns the available historical data.

    Args:
        app_id: Numeric app ID from list_apps.
        access_type: "ONGOING" (default) or "ONE_TIME_SNAPSHOT".
    """
    body = {
        "data": {
            "type": "analyticsReportRequests",
            "attributes": {"accessType": _one_of(access_type, ACCESS_TYPES, "access_type")},
            "relationships": {
                "app": {"data": {"type": "apps", "id": _resource_id(app_id, "app_id")}}
            },
        }
    }
    payload = api.post("v1/analyticsReportRequests", body)
    return _attributes(payload.get("data", {}), "accessType", "stoppedDueToInactivity")


@mcp.tool(annotations=READ_ONLY)
def list_reports(
    request_id: str,
    category: str | None = None,
    name: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List the reports available inside an analytics report request.

    Args:
        request_id: ID from list_report_requests or create_report_request.
        category: Optional category filter, see list_report_categories.
        name: Optional exact report name filter.
        limit: Reports per page (1-200).
        cursor: Pagination cursor returned by a previous call.
    """
    params: dict[str, Any] = {
        "limit": _clamp(limit, 1, 200),
        "fields[analyticsReports]": ["name", "category"],
        "filter[name]": name,
        "cursor": cursor,
    }
    if category:
        params["filter[category]"] = _one_of(category, tuple(REPORT_CATEGORIES), "category")
    path = f"v1/analyticsReportRequests/{_resource_id(request_id, 'request_id')}/reports"
    return _page(api.get(path, params), "name", "category")


@mcp.tool(annotations=READ_ONLY)
def list_report_instances(
    report_id: str,
    granularity: str | None = None,
    processing_date: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List the instances of a report: one per granularity and processing date.

    Args:
        report_id: ID from list_reports.
        granularity: Optional "DAILY", "WEEKLY" or "MONTHLY".
        processing_date: Optional "YYYY-MM-DD" date the instance was processed.
        limit: Instances per page (1-200).
        cursor: Pagination cursor returned by a previous call.
    """
    params: dict[str, Any] = {
        "limit": _clamp(limit, 1, 200),
        "fields[analyticsReportInstances]": ["granularity", "processingDate"],
        "cursor": cursor,
    }
    if granularity:
        params["filter[granularity]"] = _one_of(granularity, GRANULARITIES, "granularity")
    if processing_date:
        params["filter[processingDate]"] = api.check_date(
            processing_date, "%Y-%m-%d", "processing_date"
        )
    path = f"v1/analyticsReports/{_resource_id(report_id, 'report_id')}/instances"
    return _page(api.get(path, params), "granularity", "processingDate")


@mcp.tool(annotations=READ_ONLY)
def list_report_segments(instance_id: str, limit: int = 200) -> dict[str, Any]:
    """List the segments of a report instance, each with a download URL.

    Large reports are split into several segments. The URLs expire 5 minutes
    after this call; download_report_instance fetches and parses them for you.

    Args:
        instance_id: ID from list_report_instances.
        limit: Segments per page (1-200).
    """
    params = {
        "limit": _clamp(limit, 1, 200),
        "fields[analyticsReportSegments]": ["checksum", "sizeInBytes", "url"],
    }
    path = f"v1/analyticsReportInstances/{_resource_id(instance_id, 'instance_id')}/segments"
    return _page(api.get(path, params), "checksum", "sizeInBytes", "url")


def _download_instance(instance_id: str, max_rows: int, max_bytes: int) -> dict[str, Any]:
    segments = list_report_segments(instance_id).get("data", [])
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    truncated = False
    for segment in segments:
        url = segment.get("url")
        if not url:
            continue
        payload = api.decompress(api.download(url, max_bytes), max_bytes)
        parsed = api.parse_table(payload, max_rows - len(rows))
        columns = columns or parsed["columns"]
        rows.extend(parsed["rows"])
        truncated = truncated or parsed["truncated"]
        if len(rows) >= max_rows:
            truncated = truncated or len(segments) > 1
            break
    return {
        "instanceId": instance_id,
        "segments": len(segments),
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
    }


@mcp.tool(annotations=READ_ONLY)
def download_report_instance(
    instance_id: str,
    max_rows: int = 1000,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    """Download every segment of a report instance and return the parsed rows.

    Args:
        instance_id: ID from list_report_instances.
        max_rows: Cap on returned rows (1-20000); `truncated` flags overflow.
        max_bytes: Safety cap per segment, after decompression (up to 100MB).
    """
    return _download_instance(
        _resource_id(instance_id, "instance_id"),
        _clamp(max_rows, 1, 20_000),
        _clamp(max_bytes, 1024, 100_000_000),
    )


@mcp.tool(annotations=READ_ONLY)
def fetch_analytics_report(
    app_id: str,
    report_name: str,
    granularity: str = "DAILY",
    processing_date: str | None = None,
    access_type: str = "ONGOING",
    max_rows: int = 1000,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    """Fetch one analytics report end to end: request, report, instance, rows.

    Resolves the app's report request, finds the report by name, picks the
    instance (the latest processing date unless one is given) and downloads its
    segments. Call list_reports first if you do not know the exact report name.

    Args:
        app_id: Numeric app ID from list_apps.
        report_name: Exact report name, e.g. as returned by list_reports.
        granularity: "DAILY" (default), "WEEKLY" or "MONTHLY".
        processing_date: Optional "YYYY-MM-DD"; defaults to the latest instance.
        access_type: "ONGOING" (default) or "ONE_TIME_SNAPSHOT".
        max_rows: Cap on returned rows (1-20000).
        max_bytes: Safety cap per segment, after decompression.
    """
    granularity = _one_of(granularity, GRANULARITIES, "granularity")
    requests_page = list_report_requests(app_id, access_type=access_type)
    candidates = [
        item for item in requests_page.get("data", []) if not item.get("stoppedDueToInactivity")
    ]
    if not candidates:
        raise ValueError(
            f"No usable {access_type} analytics report request for app {app_id}. "
            "Create one with create_report_request (data shows up the next day), "
            "or check list_report_requests for requests stopped due to inactivity."
        )

    report = None
    for request in candidates:
        matches = list_reports(str(request["id"]), name=report_name).get("data", [])
        if matches:
            report = matches[0]
            break
    if report is None:
        available = sorted(
            str(item.get("name"))
            for request in candidates
            for item in list_reports(str(request["id"])).get("data", [])
        )
        raise ValueError(
            f"No report named {report_name!r} for app {app_id}. Available: {available}"
        )

    instances = list_report_instances(
        str(report["id"]), granularity=granularity, processing_date=processing_date
    ).get("data", [])
    if not instances:
        raise ValueError(
            f"No {granularity} instance of {report_name!r}"
            + (f" processed on {processing_date}" if processing_date else "")
            + ". Use list_report_instances to see which dates are available."
        )
    instance = max(instances, key=lambda item: str(item.get("processingDate") or ""))

    result = _download_instance(
        str(instance["id"]),
        _clamp(max_rows, 1, 20_000),
        _clamp(max_bytes, 1024, 100_000_000),
    )
    return {
        "appId": app_id,
        "reportId": report["id"],
        "reportName": report.get("name"),
        "category": report.get("category"),
        "granularity": granularity,
        "processingDate": instance.get("processingDate"),
        **result,
    }


@mcp.tool(annotations=READ_ONLY)
def list_sales_report_types() -> dict[str, Any]:
    """List the valid reportType/reportSubType/frequency/version combinations
    of download_sales_report. Other combinations are rejected by the API."""
    return {
        "reports": SALES_REPORT_TYPES,
        "reportDate": {
            "DAILY": "YYYY-MM-DD",
            "WEEKLY": "YYYY-MM-DD (the Sunday that ends the week)",
            "MONTHLY": "YYYY-MM",
            "YEARLY": "YYYY",
        },
        "notes": (
            "Sales data is reported in Apple's fiscal calendar and lags a day or "
            "two. The vendor number comes from $APP_STORE_CONNECT_VENDOR_NUMBER "
            "unless passed explicitly, and the API key needs the Sales or "
            "Finance role."
        ),
    }


@mcp.tool(annotations=READ_ONLY)
def download_sales_report(
    report_type: str,
    report_sub_type: str,
    frequency: str,
    report_date: str,
    version: str | None = None,
    vendor_number: str | None = None,
    max_rows: int = 1000,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    """Download a Sales and Trends report and return it as parsed rows.

    Covers units sold, proceeds, installs, subscriptions, subscribers and offer
    code redemptions. See list_sales_report_types for the valid combinations.

    Args:
        report_type: e.g. "SALES", "INSTALLS", "SUBSCRIPTION", "SUBSCRIBER".
        report_sub_type: e.g. "SUMMARY" or "DETAILED".
        frequency: "DAILY", "WEEKLY", "MONTHLY" or "YEARLY".
        report_date: Date for the frequency: "YYYY-MM-DD" for daily/weekly,
            "YYYY-MM" for monthly, "YYYY" for yearly.
        version: Report version, e.g. "1_0"; defaults to the API's default.
        vendor_number: Overrides $APP_STORE_CONNECT_VENDOR_NUMBER.
        max_rows: Cap on returned rows (1-20000).
        max_bytes: Safety cap after decompression.
    """
    frequency = _one_of(frequency, tuple(FREQUENCY_DATE_FORMAT), "frequency")
    api.check_date(report_date, FREQUENCY_DATE_FORMAT[frequency], "report_date")
    max_rows = _clamp(max_rows, 1, 20_000)
    max_bytes = _clamp(max_bytes, 1024, 100_000_000)
    params = {
        "filter[reportType]": report_type.upper(),
        "filter[reportSubType]": report_sub_type.upper(),
        "filter[frequency]": frequency,
        "filter[reportDate]": report_date,
        "filter[vendorNumber]": get_vendor_number(vendor_number),
        "filter[version]": version,
    }
    payload = api.decompress(api.get_bytes("v1/salesReports", params), max_bytes)
    return {
        "reportType": params["filter[reportType]"],
        "reportSubType": params["filter[reportSubType]"],
        "frequency": frequency,
        "reportDate": report_date,
        **api.parse_table(payload, max_rows),
    }


@mcp.tool(annotations=READ_ONLY)
def download_finance_report(
    report_date: str,
    region_code: str = "ZZ",
    report_type: str = "FINANCIAL",
    vendor_number: str | None = None,
    max_rows: int = 1000,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    """Download a finance report (payments and proceeds) as parsed rows.

    Args:
        report_date: Fiscal month, "YYYY-MM".
        region_code: Region of the report, or "ZZ" for all regions (default).
        report_type: "FINANCIAL" (default) or "FINANCE_DETAIL".
        vendor_number: Overrides $APP_STORE_CONNECT_VENDOR_NUMBER.
        max_rows: Cap on returned rows (1-20000).
        max_bytes: Safety cap after decompression.
    """
    api.check_date(report_date, "%Y-%m", "report_date")
    max_rows = _clamp(max_rows, 1, 20_000)
    max_bytes = _clamp(max_bytes, 1024, 100_000_000)
    params = {
        "filter[reportDate]": report_date,
        "filter[regionCode]": region_code.upper(),
        "filter[reportType]": _one_of(report_type, ("FINANCIAL", "FINANCE_DETAIL"), "report_type"),
        "filter[vendorNumber]": get_vendor_number(vendor_number),
    }
    payload = api.decompress(api.get_bytes("v1/financeReports", params), max_bytes)
    return {
        "reportDate": report_date,
        "regionCode": params["filter[regionCode]"],
        **api.parse_table(payload, max_rows),
    }


@mcp.tool(annotations=READ_ONLY)
def list_customer_reviews(
    app_id: str,
    rating: list[int] | None = None,
    territory: list[str] | None = None,
    sort: str = "-createdDate",
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List App Store customer reviews of an app.

    Args:
        app_id: Numeric app ID from list_apps.
        rating: Optional star ratings to keep, e.g. [1, 2].
        territory: Optional ISO 3166-1 alpha-3 territories, e.g. ["BRA", "USA"].
        sort: "-createdDate" (newest first, default), "createdDate", "rating"
            or "-rating".
        limit: Reviews per page (1-200).
        cursor: Pagination cursor returned by a previous call.
    """
    params: dict[str, Any] = {
        "limit": _clamp(limit, 1, 200),
        "sort": REVIEW_SORTS[_one_of(sort, tuple(REVIEW_SORTS), "sort")],
        "filter[rating]": rating,
        "filter[territory]": [str(item).upper() for item in territory] if territory else None,
        "fields[customerReviews]": [
            "rating", "title", "body", "reviewerNickname", "createdDate", "territory",
        ],
        "cursor": cursor,
    }
    path = f"v1/apps/{_resource_id(app_id, 'app_id')}/customerReviews"
    return _page(
        api.get(path, params),
        "rating", "title", "body", "reviewerNickname", "createdDate", "territory",
    )


@mcp.tool(annotations=READ_ONLY)
def get_perf_power_metrics(
    app_id: str,
    metric_type: str | None = None,
    device_type: str | None = None,
    platform: str = "IOS",
) -> dict[str, Any]:
    """Get the Xcode power and performance metrics of an app's recent versions.

    Covers launch time, hangs, memory, disk writes, battery and terminations,
    aggregated from devices that opted into sharing diagnostics.

    Args:
        app_id: Numeric app ID from list_apps.
        metric_type: Optional one of DISK, HANG, BATTERY, LAUNCH, MEMORY,
            ANIMATION, TERMINATION, STORAGE.
        device_type: Optional device filter, e.g. "all_iphones", "all_ipads".
        platform: Currently only "IOS".
    """
    params: dict[str, Any] = {
        "filter[platform]": _one_of(platform, ("IOS",), "platform"),
        "filter[deviceType]": device_type,
    }
    if metric_type:
        params["filter[metricType]"] = _one_of(metric_type, PERF_METRIC_TYPES, "metric_type")
    return api.get(f"v1/apps/{_resource_id(app_id, 'app_id')}/perfPowerMetrics", params)


def main() -> None:
    parser = argparse.ArgumentParser(description="App Store Connect MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
