import asyncio
import base64
import json
import logging
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.db import SessionLocal
from app.data_fusion_service import enrich_prediction, fuse_camera_context
from app.inference import model_service
from app.models import Event, InferenceRecord
from app.realtime import publish_event
from app.temporal_model import temporal_risk_service

logger = logging.getLogger("nexsafe.camera")


@dataclass
class CameraRuntime:
    state: str
    inference_fps: float | None = None
    latency_ms: float | None = None
    error: str | None = None


workers: dict[str, asyncio.Task] = {}
runtime: dict[str, CameraRuntime] = {}


def _detect_and_encode(frame, model, previous_gray):
    started = time.perf_counter()
    result = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)[0]
    latency_ms = (time.perf_counter() - started) * 1000
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    optical_flow_mean = None
    if previous_gray is not None and previous_gray.shape == gray.shape:
        flow = cv2.calcOpticalFlowFarneback(
            previous_gray, gray, None, pyr_scale=0.5, levels=3,
            winsize=15, iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        optical_flow_mean = float(cv2.magnitude(flow[..., 0], flow[..., 1]).mean())
    detections = []
    if result.boxes is not None:
        for box in result.boxes:
            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            coordinates = [int(value) for value in box.xyxy[0].tolist()]
            track_id = int(box.id.item()) if box.id is not None else None
            detections.append({
                "class_id": class_id,
                "label": model.names[class_id],
                "confidence": confidence,
                "track_id": track_id,
                "xyxy": coordinates,
            })
            x1, y1, x2, y2 = coordinates
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 229, 255), 2)
            label = f"{model.names[class_id]} {confidence:.2f}"
            if track_id is not None:
                label += f" · {track_id}"
            cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 229, 255), 1)
    encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
    return (
        detections,
        latency_ms,
        base64.b64encode(encoded).decode("ascii") if encoded_ok else None,
        gray,
        optical_flow_mean,
    )


async def _save_measurement(owner_id: str, camera_id: str, frame_count: int, average_latency: float) -> None:
    async with SessionLocal() as db:
        db.add(InferenceRecord(
            owner_id=owner_id,
            camera_id=camera_id,
            processed_frames=frame_count,
            latency_ms=average_latency,
        ))
        await db.commit()


async def _save_risk_event(owner_id: str, camera_id: str, prediction: dict) -> str:
    event = Event(
        owner_id=owner_id,
        camera_id=camera_id,
        event_type="predicted_risk",
        risk_score=prediction["risk_score"],
        model_confidence=prediction["confidence"],
        details=json.dumps({
            "prediction_type": prediction["prediction_type"],
            "predicted_class": prediction["class"],
            "model_version": prediction["model_version"],
            "sequence_frames": prediction["sequence_frames"],
            "confirmed_accident": False,
            "environmental_context": prediction.get("environmental_context"),
        }),
    )
    async with SessionLocal() as db:
        db.add(event)
        await db.commit()
        await db.refresh(event)
    return event.id


async def run_camera(
    camera_id: str,
    owner_id: str,
    source: str,
    weather_station_id: str | None = None,
) -> None:
    capture = None
    try:
        runtime[camera_id] = CameraRuntime("connecting")
        await publish_event(owner_id, {"type": "camera.status", "camera_id": camera_id, "status": "connecting"})
        tracker_model = await asyncio.to_thread(model_service.create_tracker)
        capture_source = int(source) if source.isdigit() else source
        capture = await asyncio.to_thread(cv2.VideoCapture, capture_source)
        if not capture.isOpened():
            raise ConnectionError("Camera stream could not be opened")
        last_frame = time.perf_counter()
        interval_start = last_frame
        interval_frames = 0
        interval_latency = 0.0
        total_frames = 0
        last_publish = 0.0
        last_risk_prediction = 0.0
        last_alert = 0.0
        last_weather_lookup = 0.0
        weather_context = None
        previous_gray = None
        frame_window = deque()
        runtime[camera_id] = CameraRuntime("connected")
        await publish_event(owner_id, {"type": "camera.status", "camera_id": camera_id, "status": "connected"})
        while True:
            ok, frame = await asyncio.to_thread(capture.read)
            if not ok:
                raise ConnectionError("Camera stream stopped returning frames")
            risk_frame = cv2.resize(
                frame,
                (temporal_risk_service.image_size, temporal_risk_service.image_size),
                interpolation=cv2.INTER_AREA,
            )
            detections, latency_ms, snapshot, previous_gray, optical_flow_mean = await asyncio.to_thread(
                _detect_and_encode, frame, tracker_model, previous_gray
            )
            total_frames += 1
            interval_frames += 1
            interval_latency += latency_ms
            now = time.perf_counter()
            elapsed = max(now - last_frame, 0.000001)
            fps = 1 / elapsed
            last_frame = now
            runtime[camera_id] = CameraRuntime("connected", fps, latency_ms)
            frame_window.append((now, risk_frame))
            while frame_window and now - frame_window[0][0] > temporal_risk_service.window_seconds:
                frame_window.popleft()
            prediction = None
            if (
                temporal_risk_service.available
                and len(frame_window) >= temporal_risk_service.sequence_length
                and frame_window[-1][0] - frame_window[0][0] >= temporal_risk_service.window_seconds * 0.9
                and now - last_risk_prediction >= 1.0
            ):
                sampled_indices = np.linspace(
                    0, len(frame_window) - 1, temporal_risk_service.sequence_length
                ).astype(int)
                sequence = [frame_window[index][1] for index in sampled_indices]
                prediction = await asyncio.to_thread(temporal_risk_service.predict, sequence)
                last_risk_prediction = now
                if prediction:
                    if weather_station_id and (
                        weather_context is None or now - last_weather_lookup >= 300
                    ):
                        async with SessionLocal() as db:
                            weather_context = await fuse_camera_context(db, weather_station_id)
                        last_weather_lookup = now
                    prediction = enrich_prediction(
                        prediction,
                        weather_context or {
                            "weather": {
                                "status": "not_linked",
                                "message": "No IMD station is linked to this camera.",
                                "model_input": False,
                            },
                            "fusion_status": "not_linked",
                            "weather_used_by_model": False,
                        },
                    )
                    await publish_event(owner_id, {
                        "type": "risk.prediction",
                        "camera_id": camera_id,
                        **prediction,
                        "alert_threshold": settings.accident_alert_threshold,
                    })
                    risky_classes = {
                        item.strip().lower()
                        for item in settings.accident_risk_classes.split(",")
                        if item.strip()
                    }
                    if (
                        prediction["class"].strip().lower() in risky_classes
                        and settings.accident_alert_threshold is not None
                        and prediction["risk_score"] >= settings.accident_alert_threshold
                        and now - last_alert >= 60
                    ):
                        event_id = await _save_risk_event(owner_id, camera_id, prediction)
                        await publish_event(owner_id, {
                            "type": "event.created",
                            "id": event_id,
                            "camera_id": camera_id,
                            "event_type": "predicted_risk",
                            "occurred_at": time.time(),
                            "status": "open",
                            "risk_score": prediction["risk_score"],
                            "model_confidence": prediction["confidence"],
                            "confirmed_accident": False,
                        })
                        last_alert = now
            if now - last_publish >= .2:
                await publish_event(owner_id, {
                    "type": "camera.frame",
                    "camera_id": camera_id,
                    "captured_at": time.time(),
                    "inference_fps": fps,
                    "latency_ms": latency_ms,
                    "optical_flow_mean_magnitude": optical_flow_mean,
                    "detections": detections,
                    "risk_prediction": prediction,
                    "jpeg_base64": snapshot,
                })
                last_publish = now
            if now - interval_start >= 5:
                await _save_measurement(owner_id, camera_id, interval_frames, interval_latency / interval_frames)
                interval_frames = 0
                interval_latency = 0.0
                interval_start = now
            if total_frames % 120 == 0:
                logger.info("Camera inference active camera_id=%s frames=%d", camera_id, total_frames)
    except asyncio.CancelledError:
        raise
    except (ConnectionError, cv2.error, OSError, RuntimeError) as exc:
        logger.warning("Camera processing stopped camera_id=%s error_type=%s", camera_id, type(exc).__name__)
        runtime[camera_id] = CameraRuntime("disconnected", error="Camera stream stopped or could not be opened")
        await publish_event(owner_id, {
            "type": "camera.status", "camera_id": camera_id,
            "status": "disconnected", "error": "Camera stream stopped or could not be opened",
        })
    except Exception as exc:
        logger.exception("Unexpected camera inference failure camera_id=%s", camera_id)
        runtime[camera_id] = CameraRuntime("error", error="Inference worker failed; check service logs")
        await publish_event(owner_id, {
            "type": "camera.status", "camera_id": camera_id,
            "status": "error", "error": "Inference worker failed; check service logs",
        })
    finally:
        if capture is not None:
            await asyncio.to_thread(capture.release)
        if runtime.get(camera_id, CameraRuntime("stopped")).state not in {"disconnected", "error"}:
            runtime[camera_id] = CameraRuntime("stopped")
            await publish_event(owner_id, {"type": "camera.status", "camera_id": camera_id, "status": "stopped"})
        workers.pop(camera_id, None)


def start_worker(
    camera_id: str,
    owner_id: str,
    source: str,
    weather_station_id: str | None = None,
) -> bool:
    task = workers.get(camera_id)
    if task is not None and not task.done():
        return False
    workers[camera_id] = asyncio.create_task(
        run_camera(camera_id, owner_id, source, weather_station_id)
    )
    return True


async def stop_worker(camera_id: str) -> bool:
    task = workers.get(camera_id)
    if task is None or task.done():
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return True
