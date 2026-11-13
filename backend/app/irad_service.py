from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import configured_secret, settings
from app.government_store import get_snapshot, parse_source_datetime, refresh_snapshot, snapshot_response

IRAD_PORTAL = "https://irad.parivahan.gov.in/"


def _authorized_endpoint() -> str | None:
    url = settings.irad_api_url
    token = settings.irad_api_token
    if not url or not configured_secret(token):
        return None
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.query or parsed.fragment or parsed.username or parsed.password or not (
        host == "parivahan.gov.in" or host.endswith(".parivahan.gov.in")
    ):
        raise ValueError("IRAD_API_URL must be an HTTPS endpoint on parivahan.gov.in")
    return url


async def _fetch_authorized_summary() -> tuple[dict[str, Any], datetime | None]:
    endpoint = _authorized_endpoint()
    if endpoint is None or not configured_secret(settings.irad_api_token):
        raise ValueError("iRAD data access requires an authorized endpoint and institutional token")
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {settings.irad_api_token.get_secret_value()}"},
        )
        response.raise_for_status()
        payload = response.json()
    records: Any = payload
    if isinstance(payload, dict):
        for key in ("records", "data", "results"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break
    count = len(records) if isinstance(records, list) else None
    raw_timestamp = (
        payload.get("updated_at") or payload.get("last_updated") or payload.get("timestamp")
        if isinstance(payload, dict)
        else None
    )
    return {
        "record_count": count,
        "response_shape": "list" if isinstance(payload, list) else "object",
        "data_returned": False,
        "note": "Authorized endpoint checked; accident records are not copied into the shared workspace.",
        "source": "Integrated Road Accident Database (iRAD)",
        "source_url": IRAD_PORTAL,
    }, parse_source_datetime(raw_timestamp)


async def refresh(db: AsyncSession, *, force: bool = False):
    try:
        configured = _authorized_endpoint() is not None
    except ValueError:
        configured = False
    configured = configured and configured_secret(settings.irad_api_token)
    return await refresh_snapshot(db, "irad_authorized_access", configured, _fetch_authorized_summary, force=force)


async def response(db: AsyncSession) -> dict[str, Any]:
    try:
        endpoint = _authorized_endpoint()
        configuration_error = None
    except ValueError as exc:
        endpoint = None
        configuration_error = str(exc)
    configured = endpoint is not None and configured_secret(settings.irad_api_token)
    snapshot = await get_snapshot(db, "irad_authorized_access")
    result = snapshot_response(
        snapshot,
        source_key="irad_authorized_access",
        name="iRAD institutional access",
        source_url=IRAD_PORTAL,
        configured=configured,
        data_kind="restricted",
    )
    if configuration_error:
        result["error"] = configuration_error
    elif not configured:
        result["error"] = "No public iRAD API is documented; configure an institution-authorized API endpoint and token."
    return result
