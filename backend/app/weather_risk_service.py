from datetime import datetime, timezone
from typing import Any

from app.government_store import get_snapshot
from sqlalchemy.ext.asyncio import AsyncSession


def _station_matches(value: Any, station_id: str) -> bool:
    return value is not None and str(value).strip().casefold() == station_id.strip().casefold()


async def context_for_station(db: AsyncSession, station_id: str | None) -> dict[str, Any]:
    if not station_id:
        return {
            "status": "not_linked",
            "message": "No IMD station is linked to this camera.",
            "model_input": False,
        }

    snapshot = await get_snapshot(db, "imd_observations")
    if snapshot is None or not isinstance(snapshot.payload, dict):
        return {
            "status": "unavailable",
            "station_id": station_id,
            "message": "IMD observations are not available.",
            "model_input": False,
        }
    observations = snapshot.payload.get("observations", [])
    matches = [
        item
        for item in observations
        if isinstance(item, dict) and _station_matches(item.get("station_id"), station_id)
    ]
    if not matches:
        return {
            "status": "unavailable",
            "station_id": station_id,
            "message": "No observation for the linked IMD station is cached.",
            "source": "India Meteorological Department",
            "model_input": False,
        }

    observation = max(
        matches,
        key=lambda item: item.get("observed_at") or "",
    )
    observed_at = observation.get("observed_at")
    freshness = "unknown"
    if isinstance(observed_at, str):
        try:
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            freshness = (
                "fresh"
                if -300 <= (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= 10800
                else "stale"
            )
        except ValueError:
            freshness = "timestamp_unavailable"
    if snapshot.status == "stale":
        freshness = "stale"
    return {
        "status": "available" if freshness == "fresh" else freshness,
        "station_id": station_id,
        "station": observation.get("station"),
        "observed_at": observed_at,
        "source": "India Meteorological Department",
        "source_url": snapshot.payload.get("source_url"),
        "observation": {
            key: observation.get(key)
            for key in (
                "temperature_c",
                "humidity_percent",
                "wind_speed_kmph",
                "wind_direction",
                "rainfall_24h_mm",
                "mslp_hpa",
                "weather_code",
                "nebulosity",
            )
        },
        "model_input": False,
        "message": "Weather is contextual telemetry; the configured visual model was not trained with weather inputs.",
    }
