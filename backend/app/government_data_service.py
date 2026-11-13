import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app import imd_service, irad_service, morth_service, ogd_service

logger = logging.getLogger("nexsafe.government")
refresh_requested = asyncio.Event()


async def refresh_sources(db: AsyncSession) -> None:
    for source_key, refresh in (
        ("imd_observations", imd_service.refresh_observations),
        ("imd_forecasts", imd_service.refresh_forecasts),
        ("imd_warnings", imd_service.refresh_warnings),
        ("morth_accidents", morth_service.refresh),
        ("ogd_resources", ogd_service.refresh_configured_resources),
        ("irad_authorized_access", irad_service.refresh),
    ):
        try:
            if source_key == "ogd_resources":
                await asyncio.sleep(1)
            await refresh(db)
        except Exception:
            logger.exception("Government source refresh crashed source=%s", source_key)


async def government_refresh_loop(interval_seconds: int) -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await refresh_sources(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Government data synchronization cycle failed")
        try:
            await asyncio.wait_for(refresh_requested.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
        refresh_requested.clear()


async def government_status(db: AsyncSession) -> dict:
    imd = await imd_service.responses(db)
    morth = await morth_service.response(db)
    irad = await irad_service.response(db)
    ogd_resources = await ogd_service.configured_resource_responses(db)
    return {
        "sources": {
            **imd,
            "morth_accidents": morth,
            "irad_authorized_access": irad,
            **ogd_resources,
        },
    }
