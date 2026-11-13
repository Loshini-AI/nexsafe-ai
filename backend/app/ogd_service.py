import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from app.config import configured_secret, settings
from app.government_store import parse_source_datetime
from app.government_store import get_snapshot, refresh_snapshot, snapshot_response
from sqlalchemy.ext.asyncio import AsyncSession

OGD_BASE = "https://api.data.gov.in/resource"
OGD_PORTAL = "https://www.data.gov.in/"


def _api_key() -> str:
    if not configured_secret(settings.ogd_api_key):
        raise ValueError("Configure an Open Government Data API key")
    return settings.ogd_api_key.get_secret_value()


async def fetch_resource(resource_id: str) -> tuple[dict[str, Any], datetime | None]:
    try:
        UUID(resource_id)
    except ValueError as exc:
        raise ValueError("OGD resource ID must be the UUID shown in its official catalog") from exc

    url = f"{OGD_BASE}/{resource_id}"
    page_size = 1000
    max_records = 5000
    records: list[dict[str, Any]] = []
    metadata: dict[str, Any] | None = None
    total: int | None = None
    async with httpx.AsyncClient(timeout=15) as client:
        while len(records) < max_records:
            if records:
                await asyncio.sleep(1)
            response = await client.get(
                url,
                params={
                    "api-key": _api_key(),
                    "format": "json",
                    "limit": min(page_size, max_records - len(records)),
                    "offset": len(records),
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, dict) or not isinstance(page.get("records"), list):
                raise ValueError("OGD returned an unexpected resource response")
            page_records = page["records"]
            if not all(isinstance(item, dict) for item in page_records):
                raise ValueError("OGD resource contains an unexpected record schema")
            if metadata is None:
                metadata = {key: value for key, value in page.items() if key != "records"}
                raw_total = page.get("total")
                total = int(raw_total) if str(raw_total).isdigit() else None
            records.extend(page_records)
            if not page_records or len(page_records) < page_size:
                break
            if total is not None and len(records) >= total:
                break

    if metadata is None:
        raise ValueError("OGD returned no resource metadata")
    timestamp = None
    for key in ("updated", "updated_at", "last_updated", "lastupdated", "created"):
        timestamp = parse_source_datetime(metadata.get(key))
        if timestamp:
            break
    return {
        "metadata": metadata,
        "records": records,
        "records_fetched": len(records),
        "records_total": total,
        "truncated": total is not None and len(records) < total,
        "source": "Open Government Data Platform India",
        "source_url": url,
        "catalog_url": OGD_PORTAL,
    }, timestamp


def configured_resource_ids() -> list[str]:
    ids = [value.strip() for value in settings.ogd_resource_ids.split(",") if value.strip()]
    if settings.morth_ogd_resource_id:
        ids = [value for value in ids if value != settings.morth_ogd_resource_id]
    return list(dict.fromkeys(ids))


def _snapshot_key(resource_id: str) -> str:
    return f"ogd_resource_{resource_id}"


async def refresh_configured_resources(db: AsyncSession) -> None:
    if not configured_secret(settings.ogd_api_key):
        return
    for index, resource_id in enumerate(configured_resource_ids()):
        if index:
            await asyncio.sleep(1)
        key = _snapshot_key(resource_id)
        await refresh_snapshot(
            db,
            key,
            True,
            lambda resource_id=resource_id: fetch_resource(resource_id),
        )


async def configured_resource_responses(db: AsyncSession) -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}
    configured = configured_secret(settings.ogd_api_key)
    for resource_id in configured_resource_ids():
        key = _snapshot_key(resource_id)
        snapshot = await get_snapshot(db, key)
        responses[key] = snapshot_response(
            snapshot,
            source_key=key,
            name=f"OGD dataset {resource_id}",
            source_url=f"{OGD_BASE}/{resource_id}",
            configured=configured,
            data_kind="published_dataset",
        )
    return responses
