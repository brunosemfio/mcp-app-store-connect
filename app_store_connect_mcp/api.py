"""Thin helpers over the App Store Connect REST API."""

from __future__ import annotations

import csv
import gzip
import io
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from .auth import get_token

BASE = "https://api.appstoreconnect.apple.com"
TIMEOUT = 120
GZIP_MAGIC = b"\x1f\x8b"


class AppStoreConnectApiError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_token()}"}


def _encode(params: dict[str, Any] | None) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            items = [str(item) for item in value if item is not None]
            if not items:
                continue
            encoded[key] = ",".join(items)
        elif isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        else:
            encoded[key] = value
    return encoded


def _raise_for_error(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    message = response.text
    try:
        errors = response.json().get("errors", [])
        if errors:
            message = "; ".join(
                " - ".join(part for part in (error.get("title"), error.get("detail")) if part)
                for error in errors
            )
    except ValueError:
        pass
    raise AppStoreConnectApiError(f"HTTP {response.status_code}: {message}")


def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{BASE}/{path.lstrip('/')}",
        headers=_headers(),
        params=_encode(params),
        timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.json() if response.content else {}


def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{BASE}/{path.lstrip('/')}",
        headers={**_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.json() if response.content else {}


def get_bytes(path: str, params: dict[str, Any] | None = None) -> bytes:
    response = requests.get(
        f"{BASE}/{path.lstrip('/')}",
        headers={**_headers(), "Accept": "application/a-gzip, application/json"},
        params=_encode(params),
        timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.content


def download(url: str, max_bytes: int) -> bytes:
    """Fetch an analytics report segment URL (pre-signed, valid for 5 minutes)."""
    if not url.startswith("https://"):
        raise AppStoreConnectApiError(f"Refusing to download non-HTTPS segment URL {url!r}")
    response = requests.get(url, timeout=TIMEOUT, stream=True)
    if response.status_code in (401, 403):
        response.close()
        response = requests.get(url, headers=_headers(), timeout=TIMEOUT, stream=True)
    _raise_for_error(response)
    payload = response.raw.read(max_bytes + 1, decode_content=True)
    response.close()
    if len(payload) > max_bytes:
        raise AppStoreConnectApiError(
            f"Segment is larger than max_bytes ({max_bytes}). Raise max_bytes or "
            "narrow the report (a single granularity/processing date)."
        )
    return payload


def cursor_of(payload: dict[str, Any]) -> str | None:
    """Extract the `cursor` query parameter of the response's next page link."""
    next_url = (payload.get("links") or {}).get("next")
    if not next_url:
        return None
    cursors = parse_qs(urlparse(next_url).query).get("cursor")
    return cursors[0] if cursors else None


def decompress(payload: bytes, max_bytes: int) -> bytes:
    if not payload.startswith(GZIP_MAGIC):
        return payload
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
        decompressed = compressed.read(max_bytes + 1)
    if len(decompressed) > max_bytes:
        raise AppStoreConnectApiError(
            f"Decompressed report exceeds max_bytes ({max_bytes})."
        )
    return decompressed


def parse_table(payload: bytes, max_rows: int) -> dict[str, Any]:
    """Parse a report body (TSV, or CSV as a fallback) into JSON rows."""
    text = payload.decode("utf-8-sig", errors="replace")
    sample = text.split("\n", 1)[0]
    delimiter = "\t" if "\t" in sample else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows: list[dict[str, Any]] = []
    truncated = False
    for index, row in enumerate(reader):
        if index >= max_rows:
            truncated = True
            break
        rows.append(dict(row))
    return {"columns": reader.fieldnames or [], "rows": rows, "truncated": truncated}


def check_date(value: str, fmt: str, label: str) -> str:
    try:
        datetime.strptime(value, fmt)
    except ValueError as exc:
        human = fmt.replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
        example = date.today().strftime(fmt)
        raise AppStoreConnectApiError(
            f"Invalid {label} {value!r}: expected format {human} (e.g. {example})"
        ) from exc
    return value
