"""Credential handling.

The App Store Connect API authenticates with a short-lived ES256 JWT signed by
the private key (.p8) downloaded from App Store Connect > Users and Access >
Integrations > App Store Connect API.

Configuration comes from environment variables, which may also be written to
a .env file at ~/.config/app-store-connect/.env (or $APP_STORE_CONNECT_ENV_FILE,
or .env in the working directory). Real environment variables win over the file.

- APP_STORE_CONNECT_KEY_ID: the key ID shown next to the key.
- APP_STORE_CONNECT_ISSUER_ID: the issuer ID of the team key. Leave unset for
  individual keys, which sign with `sub: user` instead of an issuer.
- APP_STORE_CONNECT_PRIVATE_KEY_PATH: path to the AuthKey_XXXXXXXXXX.p8 file,
  or APP_STORE_CONNECT_PRIVATE_KEY with the PEM contents inline.
- APP_STORE_CONNECT_VENDOR_NUMBER: vendor number, only needed by the Sales and
  Trends and Finance report tools.

The key's role decides what the tools can read: Analytics reports need at least
App Manager/Developer/Marketing access, Sales and Trends need Sales or Finance,
and Finance reports need Finance.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import jwt

AUDIENCE = "appstoreconnect-v1"
TOKEN_LIFETIME = 900
RENEW_MARGIN = 60

KEY_ID_ENV = "APP_STORE_CONNECT_KEY_ID"
ISSUER_ID_ENV = "APP_STORE_CONNECT_ISSUER_ID"
PRIVATE_KEY_ENV = "APP_STORE_CONNECT_PRIVATE_KEY"
PRIVATE_KEY_PATH_ENV = "APP_STORE_CONNECT_PRIVATE_KEY_PATH"
VENDOR_NUMBER_ENV = "APP_STORE_CONNECT_VENDOR_NUMBER"


ENV_FILE_ENV = "APP_STORE_CONNECT_ENV_FILE"
DEFAULT_ENV_FILES = (
    Path.home() / ".config" / "app-store-connect" / ".env",
    Path(".env"),
)

_env_files_loaded = False


class CredentialsError(RuntimeError):
    pass


def load_env_files() -> None:
    """Fill unset variables from the first readable .env file, once per process."""
    global _env_files_loaded
    if _env_files_loaded:
        return
    _env_files_loaded = True
    override = os.environ.get(ENV_FILE_ENV)
    candidates = (Path(override).expanduser(),) if override else DEFAULT_ENV_FILES
    for candidate in candidates:
        try:
            content = candidate.read_text()
        except OSError:
            continue
        for line in content.splitlines():
            entry = line.strip().removeprefix("export ").strip()
            if not entry or entry.startswith("#") or "=" not in entry:
                continue
            name, _, value = entry.partition("=")
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
        return


_cached_token: tuple[str, float] | None = None


def _private_key() -> str:
    inline = os.environ.get(PRIVATE_KEY_ENV)
    if inline:
        return inline.replace("\\n", "\n")
    path = os.environ.get(PRIVATE_KEY_PATH_ENV)
    if not path:
        raise CredentialsError(
            f"No private key configured. Set {PRIVATE_KEY_PATH_ENV} to the "
            f"AuthKey_XXXXXXXXXX.p8 file downloaded from App Store Connect, or "
            f"{PRIVATE_KEY_ENV} with its PEM contents."
        )
    try:
        with open(os.path.expanduser(path)) as handle:
            return handle.read()
    except OSError as exc:
        raise CredentialsError(f"Could not read private key at {path!r}: {exc}") from exc


def get_token() -> str:
    """Return a cached bearer token, signing a new one shortly before expiry."""
    global _cached_token
    load_env_files()
    now = time.time()
    if _cached_token and _cached_token[1] - now > RENEW_MARGIN:
        return _cached_token[0]

    key_id = os.environ.get(KEY_ID_ENV)
    if not key_id:
        raise CredentialsError(
            f"{KEY_ID_ENV} is not set. It is the 10-character key ID shown next "
            "to the key in App Store Connect."
        )
    issued_at = int(now)
    expires_at = issued_at + TOKEN_LIFETIME
    payload: dict[str, object] = {"iat": issued_at, "exp": expires_at, "aud": AUDIENCE}
    issuer_id = os.environ.get(ISSUER_ID_ENV)
    if issuer_id:
        payload["iss"] = issuer_id
    else:
        payload["sub"] = "user"

    try:
        token = jwt.encode(
            payload,
            _private_key(),
            algorithm="ES256",
            headers={"kid": key_id, "typ": "JWT"},
        )
    except CredentialsError:
        raise
    except Exception as exc:
        raise CredentialsError(f"Could not sign the App Store Connect token: {exc}") from exc

    _cached_token = (token, expires_at)
    return token


def get_vendor_number(explicit: str | None = None) -> str:
    """Resolve the vendor number for the sales and finance report endpoints."""
    load_env_files()
    vendor_number = explicit or os.environ.get(VENDOR_NUMBER_ENV)
    if not vendor_number:
        raise CredentialsError(
            "No vendor number given. Pass `vendor_number` or set the "
            f"{VENDOR_NUMBER_ENV} env var (App Store Connect > Payments and "
            "Financial Reports, shown as a 8-10 digit number)."
        )
    return str(vendor_number).strip()


def reset_cache() -> None:
    global _cached_token, _env_files_loaded
    _cached_token = None
    _env_files_loaded = False
