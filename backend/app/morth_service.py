from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import configured_secret, settings
from app.government_store import get_snapshot, refresh_snapshot, snapshot_response
from app.ogd_service import OGD_PORTAL, fetch_resource

MORTH_URL = "https://morth.nic.in/road-accident-in-india"


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return ""


async def _fetch_morth() -> tuple[dict[str, Any], Any]:
    resource_id = settings.morth_ogd_resource_id
    if not resource_id:
        raise ValueError("Configure MORTH_OGD_RESOURCE_ID from the official OGD catalog")
    payload, source_timestamp = await fetch_resource(resource_id)
    metadata = payload["metadata"]
    title = _text(metadata.get("title"))
    description = _text(metadata.get("desc") or metadata.get("description"))
    organizations = _text(metadata.get("org") or metadata.get("organization"))
    identity = f"{title} {description} {organizations}".casefold()
    has_accidents = "accident" in identity
    has_morth_attribution = any(
        phrase in identity
        for phrase in ("morth", "ministry of road transport", "road transport and highways")
    )
    if not (has_accidents and has_morth_attribution):
        raise ValueError(
            "The selected OGD resource does not identify a MoRTH road-accident dataset"
        )

    records = payload["records"]
    year_values: set[str] = set()
    state_values: set[str] = set()
    for record in records:
        for key, value in record.items():
            if value is None:
                continue
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            text = str(value).strip()
            if "year" in normalized and text:
                year_values.add(text)
            if normalized in {"state", "statename", "stateut", "stateutname"} and text:
                state_values.add(text)
    return {
        **payload,
        "reporting_years": sorted(year_values),
        "states_in_records": sorted(state_values),
        "data_kind": "historical_official_statistics",
        "morth_source_url": MORTH_URL,
    }, source_timestamp


async def refresh(db: AsyncSession, *, force: bool = False):
    configured = configured_secret(settings.ogd_api_key) and bool(settings.morth_ogd_resource_id)
    return await refresh_snapshot(db, "morth_accidents", configured, _fetch_morth, force=force)


async def response(db: AsyncSession) -> dict[str, Any]:
    snapshot = await get_snapshot(db, "morth_accidents")
    return snapshot_response(
        snapshot,
        source_key="morth_accidents",
        name="MoRTH historical road-accident statistics",
        source_url=MORTH_URL,
        configured=configured_secret(settings.ogd_api_key) and bool(settings.morth_ogd_resource_id),
        data_kind="historical",
        freshness_after=timedelta(days=365),
    )
