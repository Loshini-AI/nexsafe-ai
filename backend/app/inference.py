import time
import logging
import hashlib
import json
import threading
from collections import deque
from pathlib import Path

import cv2

from app.config import settings

logger = logging.getLogger("nexsafe.model")


class ModelService:
    def __init__(self) -> None:
        self.model = None
        self.error: str | None = None
        self.metadata: dict | None = None
        self.metadata_error: str | None = None
        self.lock = threading.Lock()
        self.tracker_load_lock = threading.Lock()
        if not settings.model_weights:
            self.error = "No trained model weights configured"
            logger.warning("Detector inference unavailable: %s", self.error)
            return
        weights = Path(settings.model_weights)
        if not weights.is_file():
            self.error = "Configured model weights file is unavailable"
            logger.error("%s", self.error)
            return
        try:
            from ultralytics import YOLO

            self.model = YOLO(str(weights))
            logger.info("Loaded detector checkpoint %s", weights.name)
            metadata_path = weights.with_suffix(weights.suffix + ".nexsafe.json")
            if metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    digest = hashlib.sha256()
                    with weights.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    if metadata.get("checkpoint_sha256") != digest.hexdigest():
                        self.metadata_error = "Detector metadata does not match the configured weights file"
                    elif metadata.get("architecture") == "YOLO11":
                        self.metadata = metadata
                    else:
                        self.metadata_error = "Detector metadata architecture is unsupported"
                    if self.metadata_error:
                        logger.error("%s: %s", self.metadata_error, metadata_path)
                except (OSError, json.JSONDecodeError) as exc:
                    self.metadata_error = f"Detector metadata could not be read: {type(exc).__name__}"
                    logger.exception("Detector metadata unavailable; loaded weights remain usable")
        except Exception as exc:
            logger.exception("Configured model weights could not be loaded")
            self.error = f"Model could not be loaded: {exc}"

    @property
    def available(self) -> bool:
        return self.model is not None

    def create_tracker(self):
        if not self.available or not settings.model_weights:
            raise RuntimeError("AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
        with self.tracker_load_lock:
            from ultralytics import YOLO

            return YOLO(settings.model_weights)

    def detect_frame(self, frame) -> dict:
        if not self.model:
            raise RuntimeError("AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
        started = time.perf_counter()
        with self.lock:
            result = self.model.predict(frame, verbose=False)[0]
        detections = []
        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls.item())
                detections.append({
                    "class_id": class_id,
                    "label": self.model.names[class_id],
                    "confidence": float(box.conf.item()),
                    "xyxy": [float(value) for value in box.xyxy[0].tolist()],
                })
        response = {
            "detections": detections,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "model_classes": self.model.names,
            "inference_type": "yolo_object_detection",
        }
        logger.debug(
            "Object inference completed: detections=%d latency_ms=%.2f",
            len(detections),
            response["latency_ms"],
        )
        return response

    def analyze_accident_video(self, path: str) -> dict:
        from app.temporal_model import temporal_risk_service

        if not temporal_risk_service.available:
            raise RuntimeError("AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            capture.release()
            raise ValueError("Uploaded video could not be opened")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not fps > 0:
            capture.release()
            raise ValueError("Video has no valid recorded frame rate; temporal inference disabled")
        frames_processed = 0
        predictions = []
        frame_window = deque()
        last_prediction_frame = 0
        try:
            while frames_processed < 3000:
                ok, frame = capture.read()
                if not ok:
                    break
                frames_processed += 1
                resized = cv2.resize(
                    frame,
                    (temporal_risk_service.image_size, temporal_risk_service.image_size),
                    interpolation=cv2.INTER_AREA,
                )
                frame_window.append((frames_processed / fps, resized))
                while frame_window and frame_window[-1][0] - frame_window[0][0] > temporal_risk_service.window_seconds:
                    frame_window.popleft()
                if (
                    len(frame_window) >= temporal_risk_service.sequence_length
                    and frames_processed - last_prediction_frame >= max(1, round(fps))
                    and frame_window[-1][0] - frame_window[0][0] >= temporal_risk_service.window_seconds * 0.9
                ):
                    import numpy as np

                    indices = np.linspace(
                        0, len(frame_window) - 1, temporal_risk_service.sequence_length
                    ).astype(int)
                    prediction = temporal_risk_service.predict([frame_window[index][1] for index in indices])
                    if prediction:
                        predictions.append({"frame": frames_processed - 1, **prediction})
                    last_prediction_frame = frames_processed
        finally:
            capture.release()
        if not frames_processed:
            raise ValueError("Uploaded video contains no readable frames")
        return {
            "frames_processed": frames_processed,
            "source_fps": fps,
            "predictions": predictions,
            "model_version": temporal_risk_service.version,
            "prediction_type": "temporal_model_prediction",
            "confirmed_accident": False,
        }

    def analyze_video(self, path: str) -> dict:
        if not self.model:
            raise RuntimeError("AI MODEL UNAVAILABLE — INFERENCE DISABLED.")
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            capture.release()
            raise ValueError("Uploaded video could not be opened")
        frames = 0
        detections = []
        latency_ms = 0.0
        risk_predictions = []
        from app.temporal_model import temporal_risk_service

        frame_window = deque()
        video_fps = float(capture.get(cv2.CAP_PROP_FPS))
        valid_video_fps = video_fps > 0
        try:
            tracker_model = self.create_tracker()
            while frames < 3000:
                ok, frame = capture.read()
                if not ok:
                    break
                started = time.perf_counter()
                results = tracker_model.track(
                    frame,
                    persist=True,
                    tracker="bytetrack.yaml",
                    verbose=False,
                )
                latency_ms += (time.perf_counter() - started) * 1000
                result = results[0]
                if result.boxes is not None:
                    for box in result.boxes:
                        detections.append({
                            "frame": frames,
                            "class_id": int(box.cls.item()),
                            "label": self.model.names[int(box.cls.item())],
                            "confidence": float(box.conf.item()),
                            "track_id": int(box.id.item()) if box.id is not None else None,
                            "xyxy": [float(x) for x in box.xyxy[0].tolist()],
                        })
                frames += 1
                if temporal_risk_service.available:
                    risk_frame = cv2.resize(
                        frame,
                        (temporal_risk_service.image_size, temporal_risk_service.image_size),
                        interpolation=cv2.INTER_AREA,
                    )
                    if valid_video_fps:
                        frame_window.append((frames / video_fps, risk_frame))
                        while frame_window and frame_window[-1][0] - frame_window[0][0] > temporal_risk_service.window_seconds:
                            frame_window.popleft()
                        prediction_interval = max(1, round(video_fps))
                    else:
                        prediction_interval = 1
                    if (
                        valid_video_fps
                        and len(frame_window) >= temporal_risk_service.sequence_length
                        and frame_window[-1][0] - frame_window[0][0] >= temporal_risk_service.window_seconds * 0.9
                        and frames % prediction_interval == 0
                    ):
                        import numpy as np

                        indices = np.linspace(
                            0, len(frame_window) - 1, temporal_risk_service.sequence_length
                        ).astype(int)
                        sequence = [frame_window[index][1] for index in indices]
                        prediction = temporal_risk_service.predict(sequence)
                        if prediction:
                            risk_predictions.append({"frame": frames - 1, **prediction})
        finally:
            capture.release()
        if not frames:
            raise ValueError("Uploaded video contains no readable frames")
        return {
            "frames_processed": frames,
            "inference_latency_ms_mean": latency_ms / frames if frames else None,
            "detections": detections,
            "risk_predictions": risk_predictions,
            "model": type(self.model).__name__,
            "tracking": "ByteTrack",
            "notice": (
                "Object detections only; no validated temporal risk model is configured."
                if not temporal_risk_service.available
                else "Video FPS metadata unavailable; temporal predictions were disabled for this file."
                if not valid_video_fps
                else "Temporal predictions are model outputs, not confirmed accidents."
            ),
        }


model_service = ModelService()
