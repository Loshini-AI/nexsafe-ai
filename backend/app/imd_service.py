import asyncio
import math
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import configured_secret, settings
from app.government_store import (
    get_snapshot,
    parse_source_datetime,
    refresh_snapshot,
    snapshot_response,
)

IMD_BASE = "https://api.imd.gov.in"
REFERENCE_URL = "https://api.imd.gov.in/public/api_reference.html"


def _headers() -> dict[str, str]:
    if not configured_secret(settings.imd_api_key):
        return {}
    if not settings.imd_auth_header or not re.fullmatch(
        r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", settings.imd_auth_header
    ):
        raise ValueError("Set IMD_AUTH_HEADER exactly as specified by the issued IMD API credentials")
    if settings.imd_auth_scheme and not re.fullmatch(r"[A-Za-z0-9_-]+", settings.imd_auth_scheme):
        raise ValueError("IMD_AUTH_SCHEME contains invalid characters")
    key = settings.imd_api_key.get_secret_value()
    value = f"{settings.imd_auth_scheme} {key}".strip()
    return {settings.imd_auth_header: value}


def _credentials_configured() -> bool:
    return configured_secret(settings.imd_api_key) and bool(settings.imd_auth_header)


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("IMD returned an unexpected observation schema")
        return payload
    if isinstance(payload, dict):
        for key in ("data", "observations", "current_wx", "warnings"):
            candidate = payload.get(key)
            if isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate):
                return candidate
        if any(key in payload for key in ("Station Id", "station_id", "Station", "station")):
            return [payload]
    raise ValueError("IMD returned an unexpected observation schema")


def _value(record: dict[str, Any], *names: str) -> Any:
    normalized = {
        "".join(character.lower() for character in key if character.isalnum()): value
        for key, value in record.items()
        if isinstance(key, str)
    }
    for name in names:
        match = normalized.get("".join(character.lower() for character in name if character.isalnum()))
        if match is not None:
            return match
    return None


def _normalize_observation(record: dict[str, Any]) -> dict[str, Any]:
    date = _value(record, "Date of Observation", "Date", "observation_date")
    time = _value(record, "Time of Observation", "Time", "observation_time")
    timestamp = None
    if isinstance(date, str):
        timestamp = parse_source_datetime(f"{date}T{time or '00:00:00'}+00:00")
        if timestamp is None:
            timestamp = parse_source_datetime(date)
    station_id = _value(record, "Station Id", "Station ID", "Station_Code", "station_id")
    if station_id is None or timestamp is None:
        raise ValueError("IMD observation is missing its station identifier or observation time")

    def numeric_value(*names: str) -> float | None:
        value = _value(record, *names)
        if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "na", "n/a", "-"}):
            return None
        try:
            normalized = float(value)
            if not math.isfinite(normalized):
                raise ValueError("IMD observation contains a non-finite measurement")
            return normalized
        except (TypeError, ValueError) as exc:
            raise ValueError("IMD observation contains a non-numeric measurement") from exc

    temperature = numeric_value("Temperature", "temperature_c")
    humidity = numeric_value("Humidity", "humidity_percent")
    wind_speed = numeric_value("Wind Speed", "wind_speed_kmph")
    rainfall = numeric_value("Last 24 hrs Rainfall", "Rainfall", "rainfall_24h_mm")
    pressure = numeric_value("M.S.L.P", "MSLP", "pressure")
    if humidity is not None and not 0 <= humidity <= 100:
        raise ValueError("IMD humidity is outside the valid percentage range")
    if any(value is not None and value < 0 for value in (wind_speed, rainfall)):
        raise ValueError("IMD wind speed or rainfall is negative")
    return {
        "station_id": station_id,
        "station": _value(record, "Station", "Station_Name", "station_name"),
        "observed_at": timestamp.isoformat() if timestamp else None,
        "temperature_c": temperature,
        "humidity_percent": humidity,
        "wind_speed_kmph": wind_speed,
        "wind_direction": _value(record, "Wind Direction", "wind_direction"),
        "rainfall_24h_mm": rainfall,
        "mslp_hpa": pressure,
        "weather_code": _value(record, "Weather Code", "weather_code"),
        "nebulosity": _value(record, "Nebulosity", "nebulosity"),
    }


def _city_ids() -> list[str]:
    return [value.strip() for value in settings.imd_city_ids.split(",") if value.strip()]


def _station_ids() -> list[str]:
    return [value.strip() for value in settings.imd_station_ids.split(",") if value.strip()]


async def _get_json(client: httpx.AsyncClient, url: str, *, params: dict[str, str] | None = None) -> Any:
    response = await client.get(url, params=params, headers=_headers())
    response.raise_for_status()
    return response.json()


async def _fetch_observations() -> tuple[dict[str, Any], Any]:
    station_ids = _station_ids()
    if not station_ids:
        raise ValueError("Configure IMD_STATION_IDS using official station identifiers")
    async with httpx.AsyncClient(timeout=12) as client:
        records: list[dict[str, Any]] = []
        for index, station_id in enumerate(station_ids):
            if index:
                await asyncio.sleep(1)
            payload = await _get_json(
                client,
                f"{IMD_BASE}/api/v1/current_wx",
                params={"id": station_id},
            )
            observations = [_normalize_observation(item) for item in _items(payload)]
            if any(str(item["station_id"]).strip() != station_id for item in observations):
                raise ValueError("IMD returned an observation for a different station ID")
            records.extend(observations)
    timestamps = [
        parse_source_datetime(item["observed_at"])
        for item in records
        if item["observed_at"] is not None
    ]
    latest = max(timestamps) if timestamps else None
    return {
        "observations": records,
        "station_ids_requested": station_ids,
        "record_count": len(records),
        "source": "India Meteorological Department",
        "source_url": f"{IMD_BASE}/api/v1/current_wx",
        "observation_times_are_utc": True,
    }, latest


async def _fetch_forecasts() -> tuple[dict[str, Any], Any]:
    city_ids = _city_ids()
    if not city_ids:
        raise ValueError("Configure IMD_CITY_IDS using official IMD forecast identifiers")
    async with httpx.AsyncClient(timeout=12) as client:
        forecasts = []
        for index, city_id in enumerate(city_ids):
            if index:
                await asyncio.sleep(1)
            payload = await _get_json(
                client,
                f"{IMD_BASE}/api/v1/cityforecast",
                params={"id": city_id},
            )
            if not isinstance(payload, (dict, list)):
                raise ValueError("IMD returned an unexpected forecast schema")
            forecasts.append({"city_id": city_id, "forecast": payload})
    return {
        "forecasts": forecasts,
        "city_ids_requested": city_ids,
        "source": "India Meteorological Department",
        "source_url": f"{IMD_BASE}/api/v1/cityforecast",
        "data_kind": "forecast",
    }, None


def _warnings_url() -> str | None:
    value = settings.imd_warnings_url
    if not value:
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.imd.gov.in"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("IMD_WARNINGS_URL must be an HTTPS api.imd.gov.in endpoint without embedded credentials")
    return value


async def _fetch_warnings() -> tuple[dict[str, Any], Any]:
    url = _warnings_url()
    if url is None:
        raise ValueError("Configure an IMD warnings endpoint documented for your account")
    async with httpx.AsyncClient(timeout=12) as client:
        payload = await _get_json(client, url)
    records = _items(payload)
    timestamps = [
        parse_source_datetime(_value(record, "issued_at", "updated_at", "issue_time", "date"))
        for record in records
    ]
    valid_timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return {
        "warnings": records,
        "record_count": len(records),
        "source": "India Meteorological Department",
        "source_url": url,
    }, max(valid_timestamps) if valid_timestamps else None


async def refresh_observations(db: AsyncSession, *, force: bool = False):
    configured = _credentials_configured() and bool(_station_ids())
    return await refresh_snapshot(db, "imd_observations", configured, _fetch_observations, force=force)


async def refresh_forecasts(db: AsyncSession, *, force: bool = False):
    configured = _credentials_configured() and bool(_city_ids())
    return await refresh_snapshot(db, "imd_forecasts", configured, _fetch_forecasts, force=force)


async def refresh_warnings(db: AsyncSession, *, force: bool = False):
    try:
        configured = _credentials_configured() and _warnings_url() is not None
    except ValueError:
        configured = False
    return await refresh_snapshot(db, "imd_warnings", configured, _fetch_warnings, force=force)


def _warnings_configured() -> bool:
    if not _credentials_configured():
        return False
    try:
        return _warnings_url() is not None
    except ValueError:
        return False


async def responses(db: AsyncSession) -> dict[str, dict[str, Any]]:
    observations = await get_snapshot(db, "imd_observations")
    forecasts = await get_snapshot(db, "imd_forecasts")
    warnings = await get_snapshot(db, "imd_warnings")
    warning_response = snapshot_response(
        warnings,
        source_key="imd_warnings",
        name="IMD weather warnings",
        source_url=settings.imd_warnings_url or REFERENCE_URL,
        configured=_warnings_configured(),
        data_kind="warning",
    )
    if settings.imd_warnings_url and _credentials_configured():
        try:
            _warnings_url()
        except ValueError as exc:
            warning_response["error"] = str(exc)
    return {
        "imd_observations": snapshot_response(
            observations,
            source_key="imd_observations",
            name="IMD current station observations",
            source_url=f"{IMD_BASE}/api/v1/current_wx",
            configured=_credentials_configured() and bool(_station_ids()),
            data_kind="observation",
            freshness_after=timedelta(hours=3),
        ),
        "imd_forecasts": snapshot_response(
            forecasts,
            source_key="imd_forecasts",
            name="IMD city forecasts",
            source_url=f"{IMD_BASE}/api/v1/cityforecast",
            configured=_credentials_configured() and bool(_city_ids()),
            data_kind="forecast",
        ),
        "imd_warnings": warning_response,
    }
