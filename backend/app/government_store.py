import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import GovernmentDataSnapshot

logger = logging.getLogger("nexsafe.government")
_locks: dict[str, asyncio.Lock] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_source_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


async def get_snapshot(db: AsyncSession, source_key: str) -> GovernmentDataSnapshot | None:
    return await db.get(GovernmentDataSnapshot, source_key)


async def refresh_snapshot(
    db: AsyncSession,
    source_key: str,
    configured: bool,
    fetch: Callable[[], Awaitable[tuple[dict[str, Any], datetime | None]]],
    *,
    force: bool = False,
) -> GovernmentDataSnapshot | None:
    if not configured:
        return await get_snapshot(db, source_key)

    lock = _locks.setdefault(source_key, asyncio.Lock())
    async with lock:
        snapshot = await get_snapshot(db, source_key)
        now = utc_now()
        interval = timedelta(seconds=settings.government_data_refresh_seconds)
        if (
            not force
            and snapshot is not None
            and snapshot.last_attempt_at is not None
            and now - snapshot.last_attempt_at < interval
        ):
            return snapshot

        if snapshot is None:
            snapshot = GovernmentDataSnapshot(source_key=source_key, status="unavailable")
            db.add(snapshot)
        snapshot.last_attempt_at = now
        try:
            payload, source_timestamp = await fetch()
        except (httpx.HTTPError, ValueError) as exc:
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            snapshot.status = "stale" if snapshot.payload is not None else "unavailable"
            if isinstance(exc, ValueError):
                snapshot.error = str(exc)
            elif status_code is not None:
                snapshot.error = f"Government data source temporarily unavailable (HTTP {status_code})."
            else:
                snapshot.error = "Government data source temporarily unavailable."
            logger.warning(
                "Government source refresh failed source=%s status_code=%s error_type=%s",
                source_key,
                status_code,
                type(exc).__name__,
            )
        else:
            snapshot.payload = payload
            snapshot.source_timestamp = source_timestamp
            snapshot.last_success_at = now
            snapshot.status = "connected"
            snapshot.error = None
        await db.commit()
        await db.refresh(snapshot)
        return snapshot


def snapshot_response(
    snapshot: GovernmentDataSnapshot | None,
    *,
    source_key: str,
    name: str,
    source_url: str,
    configured: bool,
    data_kind: str,
    freshness_after: timedelta | None = None,
) -> dict[str, Any]:
    status = snapshot.status if snapshot is not None else "unavailable"
    error = snapshot.error if snapshot is not None else None
    if not configured:
        status = "not_configured"
        error = "Configure authorized credentials and identifiers to enable this source."
    freshness = "unknown"
    if snapshot is not None and snapshot.payload is not None:
        if not configured or snapshot.status == "stale":
            freshness = "stale"
        elif data_kind == "historical":
            freshness = "historical"
        elif snapshot.source_timestamp is None:
            freshness = "timestamp_unavailable"
        elif freshness_after is not None:
            age = utc_now() - snapshot.source_timestamp
            freshness = "fresh" if timedelta(minutes=-5) <= age <= freshness_after else "stale"
        else:
            freshness = "verified"
    return {
        "key": source_key,
        "name": name,
        "source_url": source_url,
        "status": status,
        "freshness": freshness,
        "data_kind": data_kind,
        "source_timestamp": snapshot.source_timestamp if snapshot is not None else None,
        "last_successful_sync": snapshot.last_success_at if snapshot is not None else None,
        "last_attempt": snapshot.last_attempt_at if snapshot is not None else None,
        "error": error,
        "data": snapshot.payload if snapshot is not None else None,
    }
