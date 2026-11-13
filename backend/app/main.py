import logging
import os
import tempfile
import base64
import hashlib
import asyncio
import json
import cv2
import numpy as np
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4
from cryptography.fernet import Fernet

import httpx
from jose import JWTError, jwt
from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.camera_worker import runtime as camera_runtime, start_worker, stop_worker, workers
from app.db import engine, get_db, initialize_database, SessionLocal
from app.dataset_status import load_dataset_status
from app.government_data_service import government_refresh_loop, refresh_requested, government_status
from app.inference import model_service
from app.models import Camera, Event, InferenceRecord, User, UserSession
from app.realtime import publish_event, redis_available, redis_client, subscribe
from app.schemas import CameraCreate, CameraOut, EventOut, EventUpdate, RegistrationRequest, Token
from app.security import authenticate_token, current_user, create_token, hash_password, oauth2, verify_password
from app.temporal_model import temporal_risk_service
from app.structured_risk_service import structured_risk_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexsafe")
_fernet_key = base64.urlsafe_b64encode(hashlib.sha256(settings.camera_encryption_key.encode()).digest())
camera_cipher = Fernet(_fernet_key)


@asynccontextmanager
async def lifespan(_: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    await initialize_database()
    government_task = asyncio.create_task(
        government_refresh_loop(settings.government_data_refresh_seconds)
    )
    yield
    government_task.cancel()
    try:
        await government_task
    except asyncio.CancelledError:
        pass
    for camera_id in list(workers):
        await stop_worker(camera_id)
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="NexSafe AI", version="1.0.0", lifespan=lifespan)
frontend_origins = [
    origin.strip()
    for origin in settings.frontend_origin.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def validate_camera_source(source: str) -> None:
    parsed = urlparse(source)
    if source.isdigit():
        return
    if parsed.scheme not in {"rtsp", "rtsps", "http", "https"} or not parsed.hostname:
        raise HTTPException(422, "Camera source must be a device index or rtsp(s)/http(s) URL")
    allowed_hosts = {host.strip().lower().rstrip(".") for host in settings.camera_allowed_hosts.split(",") if host.strip()}
    if parsed.hostname.lower().rstrip(".") not in allowed_hosts:
        raise HTTPException(422, "Camera stream host is not in CAMERA_ALLOWED_HOSTS")


@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    services = {"database": "unavailable", "redis": "unavailable"}
    try:
        await db.execute(select(1))
        services["database"] = "available"
    except Exception:
        logger.exception("Database health check failed")
    try:
        redis_connected = await redis_available()
        if redis_connected:
            services["redis"] = "available"
        else:
            services["realtime"] = "process_local"
    except Exception:
        logger.exception("Redis health check failed")
        services["realtime"] = "unavailable"
    if services["redis"] == "available":
        services["realtime"] = "redis"
    return {
        "status": "available" if services["database"] == "available" and services["realtime"] != "unavailable" else "degraded",
        "services": services,
        "checked_at": datetime.now(timezone.utc),
    }


@app.get("/api/model")
async def model_status():
    return {
        "status": "loaded" if model_service.available else "unavailable",
        "message": None if model_service.available else model_service.error,
        "architecture": "Ultralytics YOLO object detector" if model_service.available else None,
        "weights_configured": bool(settings.model_weights),
        "detector": {
            "status": "loaded" if model_service.available else "unavailable",
            "error": model_service.error,
            "architecture": "Ultralytics YOLO object detector" if model_service.available else None,
            "classes": (
                list(model_service.model.names.values())
                if model_service.available and isinstance(model_service.model.names, dict)
                else []
            ),
            "model_version": model_service.metadata.get("model_version") if model_service.metadata else None,
            "dataset": model_service.metadata.get("dataset") if model_service.metadata else None,
            "training_metrics": model_service.metadata.get("training_metrics") if model_service.metadata else None,
            "validation_metrics": model_service.metadata.get("validation_metrics") if model_service.metadata else None,
            "test_metrics": model_service.metadata.get("test_metrics") if model_service.metadata else None,
            "metrics_note": (
                model_service.metadata.get("metrics_note")
                if model_service.metadata
                else model_service.metadata_error or "No verified checkpoint metadata is available."
            ),
            "training_info": model_service.metadata.get("training_info") if model_service.metadata else None,
        },
        "accident_classifier": {
            "status": "loaded" if temporal_risk_service.available else "unavailable",
            "architecture": "CNN-LSTM" if temporal_risk_service.available else None,
            "message": None if temporal_risk_service.available else temporal_risk_service.error,
            "version": temporal_risk_service.version,
            "classes": temporal_risk_service.classes,
            "evaluation_metrics": temporal_risk_service.metrics,
            "test_metrics": temporal_risk_service.test_metrics,
            "training_info": temporal_risk_service.dataset_info,
        },
        "structured_road_risk": {
            "status": "loaded" if structured_risk_service.available else "unavailable",
            "architecture": "RoadRiskMLP" if structured_risk_service.available else None,
            "message": None if structured_risk_service.available else structured_risk_service.error,
            "version": structured_risk_service.version,
            "features": structured_risk_service.feature_names,
            "classes": structured_risk_service.classes,
            "evaluation_metrics": structured_risk_service.metrics,
            "training_info": structured_risk_service.training_info,
        },
    }


@app.get("/api/datasets/status")
async def datasets_status():
    return load_dataset_status()


@app.post("/api/auth/register", response_model=Token, status_code=201)
async def register(payload: RegistrationRequest, db: AsyncSession = Depends(get_db)):
    try:
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(724190342)"))
        elif db.get_bind().dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        email = payload.email
        existing_users = await db.scalar(select(func.count(User.id))) or 0
        if existing_users and not settings.allow_registration:
            raise HTTPException(403, "Account registration is disabled")
        if await db.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(409, "Account already exists")
        user = User(
            full_name=payload.full_name,
            email=email,
            password_hash=hash_password(payload.password),
            role="admin" if existing_users == 0 else "operator",
        )
        db.add(user)
        await db.flush()
        session_id = str(uuid4())
        access_token, expires_at = create_token(user.id, session_id)
        db.add(UserSession(id=session_id, user_id=user.id, expires_at=expires_at))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Account already exists") from exc
    except (SQLAlchemyError, OSError) as exc:
        await db.rollback()
        logger.exception("Account registration failed because of a database error")
        raise HTTPException(
            500,
            "Account registration is temporarily unavailable because the database could not be reached",
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    return Token(access_token=access_token)


@app.get("/api/auth/registration")
async def registration_status(db: AsyncSession = Depends(get_db)):
    try:
        existing_users = await db.scalar(select(func.count(User.id))) or 0
    except (SQLAlchemyError, OSError) as exc:
        logger.exception("Account registration status failed because of a database error")
        raise HTTPException(
            500,
            "Account registration is temporarily unavailable because the database could not be reached",
        ) from exc
    return {
        "available": existing_users == 0 or settings.allow_registration,
        "first_account": existing_users == 0,
    }


@app.post("/api/auth/token", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    try:
        user = await db.scalar(select(User).where(User.email == form.username.strip().lower()))
    except (SQLAlchemyError, OSError) as exc:
        logger.exception("Sign-in failed because of a database error")
        raise HTTPException(
            500,
            "Sign-in is temporarily unavailable because the database could not be reached",
        ) from exc
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    session_id = str(uuid4())
    access_token, expires_at = create_token(user.id, session_id)
    db.add(UserSession(id=session_id, user_id=user.id, expires_at=expires_at))
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Sign-in session could not be saved")
        raise HTTPException(500, "Sign-in is temporarily unavailable") from exc
    return Token(access_token=access_token)


@app.post("/api/auth/logout", status_code=204)
async def logout(
    token: str = Depends(oauth2),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        session_id = claims.get("jti")
        user_id = claims.get("sub")
        if not isinstance(session_id, str) or not isinstance(user_id, str):
            raise HTTPException(401, "Invalid or expired token")
        session = await db.scalar(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        )
        if session is None:
            raise HTTPException(401, "Invalid, expired, or revoked token")
        session.revoked_at = int(datetime.now(timezone.utc).timestamp())
        await db.commit()
    except HTTPException:
        raise
    except JWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc
    except (SQLAlchemyError, OSError) as exc:
        await db.rollback()
        logger.exception("Logout failed because the session could not be revoked")
        raise HTTPException(500, "Logout is temporarily unavailable") from exc
    return Response(status_code=204)


@app.get("/api/cameras", response_model=list[CameraOut])
async def list_cameras(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    cameras = (await db.scalars(
        select(Camera).where(Camera.owner_id == user.id).order_by(Camera.created_at.desc())
    )).all()
    return [
        {
            "id": camera.id,
            "name": camera.name,
            "latitude": camera.latitude,
            "longitude": camera.longitude,
            "weather_station_id": camera.weather_station_id,
            "enabled": camera.enabled,
            "created_at": camera.created_at,
            "connection_status": (
                camera_runtime[camera.id].state
                if camera.id in camera_runtime
                else "not_started"
            ),
        }
        for camera in cameras
    ]


@app.post("/api/cameras", response_model=CameraOut, status_code=201)
async def create_camera(payload: CameraCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    validate_camera_source(payload.source)
    values = payload.model_dump()
    values["source"] = camera_cipher.encrypt(payload.source.encode()).decode()
    camera = Camera(**values, owner_id=user.id)
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return {
        "id": camera.id,
        "name": camera.name,
        "latitude": camera.latitude,
        "longitude": camera.longitude,
        "weather_station_id": camera.weather_station_id,
        "enabled": camera.enabled,
        "created_at": camera.created_at,
        "connection_status": "not_started",
    }


@app.delete("/api/cameras/{camera_id}", status_code=204)
async def delete_camera(camera_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if camera is None or camera.owner_id != user.id:
        raise HTTPException(404, "Camera not found")
    await stop_worker(camera_id)
    events = await db.scalars(select(Event).where(Event.camera_id == camera_id, Event.owner_id == user.id))
    for event in events:
        event.camera_id = None
    await db.delete(camera)
    await db.commit()


@app.post("/api/cameras/{camera_id}/start")
async def start_camera(camera_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if camera is None or camera.owner_id != user.id:
        raise HTTPException(404, "Camera not found")
    if not model_service.available:
        raise HTTPException(503, "AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
    source = camera_cipher.decrypt(camera.source.encode()).decode()
    if not start_worker(camera.id, user.id, source, camera.weather_station_id):
        raise HTTPException(409, "Camera processing is already active")
    return {"status": "connecting", "camera_id": camera.id}


@app.post("/api/cameras/{camera_id}/stop")
async def stop_camera(camera_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if camera is None or camera.owner_id != user.id:
        raise HTTPException(404, "Camera not found")
    stopped = await stop_worker(camera_id)
    return {"status": "stopped", "was_active": stopped}


@app.post("/api/videos/analyze")
@app.post("/api/inference/vehicle-tracking")
async def analyze_video(file: UploadFile = File(...), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    extensions = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/webm": ".webm",
    }
    if file.content_type not in extensions:
        raise HTTPException(415, "Unsupported video format")
    if not model_service.available:
        raise HTTPException(503, "AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
    path = ""
    try:
        fd, path = tempfile.mkstemp(suffix=extensions[file.content_type], dir=settings.upload_dir)
        size = 0
        with os.fdopen(fd, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 200 * 1024 * 1024:
                    raise HTTPException(413, "Video exceeds the 200 MB upload limit")
                target.write(chunk)
        result = await asyncio.to_thread(model_service.analyze_video, path)
        db.add(InferenceRecord(owner_id=user.id, processed_frames=result["frames_processed"],
                               latency_ms=result["inference_latency_ms_mean"] or 0))
        risk_classes = {
            item.strip().lower()
            for item in settings.accident_risk_classes.split(",")
            if item.strip()
        }
        qualifying_predictions = [
            prediction
            for prediction in result["risk_predictions"]
            if settings.accident_alert_threshold is not None
            and prediction["class"].strip().lower() in risk_classes
            and prediction["risk_score"] >= settings.accident_alert_threshold
        ]
        highest_risk = max(qualifying_predictions, key=lambda item: item["risk_score"], default=None)
        if highest_risk is not None:
            db.add(Event(
                owner_id=user.id,
                event_type="predicted_risk",
                risk_score=highest_risk["risk_score"],
                model_confidence=highest_risk["confidence"],
                details=json.dumps({
                    "prediction_type": highest_risk["prediction_type"],
                    "predicted_class": highest_risk["class"],
                    "model_version": highest_risk["model_version"],
                    "video_frame": highest_risk["frame"],
                    "confirmed_accident": False,
                }),
            ))
        await db.commit()
        if highest_risk is not None:
            await publish_event(user.id, {
                "type": "video.risk_prediction",
                **highest_risk,
                "confirmed_accident": False,
            })
        return result
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if path and os.path.exists(path):
            os.remove(path)
        await file.close()


@app.post("/api/inference/vehicle-detection")
async def detect_image(file: UploadFile = File(...), user: User = Depends(current_user)):
    del user
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Supported image types are JPEG, PNG, and WebP")
    if not model_service.available:
        raise HTTPException(503, "AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
    content = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds the 20 MB upload limit")
    frame = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(422, "Uploaded file is not a readable image")
    try:
        result = await asyncio.to_thread(model_service.detect_frame, frame)
        return {
            **result,
            "image_dimensions": {
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
            },
        }
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/inference/accident-detection")
async def detect_accident_video(file: UploadFile = File(...), user: User = Depends(current_user)):
    del user
    extensions = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/webm": ".webm",
    }
    if file.content_type not in extensions:
        raise HTTPException(415, "Unsupported video format")
    if not temporal_risk_service.available:
        raise HTTPException(503, "AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
    path = ""
    try:
        fd, path = tempfile.mkstemp(suffix=extensions[file.content_type], dir=settings.upload_dir)
        size = 0
        with os.fdopen(fd, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 200 * 1024 * 1024:
                    raise HTTPException(413, "Video exceeds the 200 MB upload limit")
                target.write(chunk)
        return await asyncio.to_thread(model_service.analyze_accident_video, path)
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if path and os.path.exists(path):
            os.remove(path)
        await file.close()


@app.post("/api/inference/road-risk")
async def predict_road_risk(
    payload: dict[str, object] = Body(...),
    user: User = Depends(current_user),
):
    del user
    try:
        return structured_risk_service.predict(payload)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/events", response_model=list[EventOut])
async def list_events(limit: int = Query(default=100, ge=1, le=500), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return list((await db.scalars(select(Event).where(Event.owner_id == user.id).order_by(Event.occurred_at.desc()).limit(limit))).all())


@app.patch("/api/events/{event_id}", response_model=EventOut)
async def update_event(event_id: str, payload: EventUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    event = await db.get(Event, event_id)
    if event is None or event.owner_id != user.id:
        raise HTTPException(404, "Event not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, key, value)
    await db.commit()
    await db.refresh(event)
    await subscribe_event_update(event, user.id)
    return event


async def subscribe_event_update(event: Event, user_id: str) -> None:
    from app.realtime import publish_event

    await publish_event(user_id, {"type": "event.updated", "id": event.id, "status": event.status})


@app.get("/api/analytics")
async def analytics(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count(Event.id)).where(Event.owner_id == user.id)) or 0
    if count < 5:
        return {"status": "insufficient_data", "message": "INSUFFICIENT DATA FOR ANALYSIS.",
                "event_count": count, "events_by_day": [], "by_type": []}
    by_day = await db.execute(select(func.date(Event.occurred_at), func.count(Event.id)).where(Event.owner_id == user.id)
                              .group_by(func.date(Event.occurred_at)).order_by(func.date(Event.occurred_at)))
    by_type = await db.execute(select(Event.event_type, func.count(Event.id)).where(Event.owner_id == user.id).group_by(Event.event_type))
    return {"status": "available", "event_count": count,
            "events_by_day": [{"date": str(day), "count": n} for day, n in by_day],
            "by_type": [{"type": kind, "count": n} for kind, n in by_type]}


@app.get("/api/overview")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    cameras = await db.scalar(select(func.count(Camera.id)).where(Camera.owner_id == user.id, Camera.enabled.is_(True))) or 0
    events = await db.scalar(
        select(func.count(Event.id)).where(Event.owner_id == user.id, Event.status != "resolved")
    ) or 0
    frames = await db.scalar(select(func.coalesce(func.sum(InferenceRecord.processed_frames), 0)).where(InferenceRecord.owner_id == user.id)) or 0
    latency = await db.scalar(
        select(func.sum(InferenceRecord.latency_ms * InferenceRecord.processed_frames)
               / func.nullif(func.sum(InferenceRecord.processed_frames), 0))
        .where(InferenceRecord.owner_id == user.id)
    )
    owned_cameras = await db.scalars(select(Camera.id).where(Camera.owner_id == user.id))
    owned_ids = set(owned_cameras.all())
    connected = sum(camera_runtime.get(camera_id) is not None and camera_runtime[camera_id].state == "connected"
                    for camera_id in owned_ids)
    current_fps = [camera_runtime[camera_id].inference_fps for camera_id in owned_ids
                   if camera_id in camera_runtime and camera_runtime[camera_id].inference_fps is not None]
    return {"connected_cameras": connected, "registered_cameras": cameras, "active_incidents": events,
            "processed_frames": frames, "inference_latency_ms": latency,
            "current_inference_fps": sum(current_fps) if current_fps else None,
            "inference_status": "available" if model_service.available else "unavailable",
            "camera_status_note": "Live connected count is based on active stream workers"}


@app.get("/api/system")
async def system_metrics(_: User = Depends(current_user)):
    import psutil

    cpu_percent, memory = await asyncio.gather(
        asyncio.to_thread(psutil.cpu_percent, 0.1),
        asyncio.to_thread(psutil.virtual_memory),
    )
    gpu = {"available": False, "memory_total_bytes": None, "memory_used_bytes": None}
    try:
        import torch

        gpu["available"] = torch.cuda.is_available()
        if gpu["available"]:
            free, total = torch.cuda.mem_get_info()
            gpu["memory_total_bytes"] = total
            gpu["memory_used_bytes"] = total - free
    except (ImportError, RuntimeError):
        logger.info("GPU metrics unavailable")
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "memory_used_bytes": memory.used,
        "memory_total_bytes": memory.total,
        "gpu": gpu,
        "measured_at": datetime.now(timezone.utc),
    }


@app.get("/api/weather")
async def weather(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180),
                  _: User = Depends(current_user)):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast",
                                        params={"latitude": latitude, "longitude": longitude,
                                                "current": "temperature_2m,precipitation,weather_code"})
            response.raise_for_status()
            return {"source": "Open-Meteo", "limitations": "Current weather only; not an accident-risk prediction",
                    "data": response.json()}
    except httpx.HTTPError as exc:
        logger.warning("Weather provider unavailable: %s", exc)
        raise HTTPException(502, "Weather provider unavailable") from exc


@app.get("/api/government")
async def government_data(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    del user
    return await government_status(db)


@app.post("/api/government/refresh", status_code=202)
async def request_government_refresh(user: User = Depends(current_user)):
    del user
    refresh_requested.set()
    return {"status": "refresh_requested"}


@app.websocket("/api/ws")
async def websocket_events(websocket: WebSocket, token: str = Query()):
    async with SessionLocal() as db:
        try:
            user = await authenticate_token(db, token)
        except HTTPException:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return
    try:
        await subscribe(websocket, user.id)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
