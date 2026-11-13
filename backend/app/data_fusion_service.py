from typing import Any

from app.weather_risk_service import context_for_station
from sqlalchemy.ext.asyncio import AsyncSession


async def fuse_camera_context(db: AsyncSession, station_id: str | None) -> dict[str, Any]:
    weather = await context_for_station(db, station_id)
    return {
        "weather": weather,
        "fusion_status": "context_attached" if weather["status"] == "available" else weather["status"],
        "weather_used_by_model": False,
    }


def enrich_prediction(prediction: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        **prediction,
        "environmental_context": context,
        "weather_used_by_model": False,
    }
