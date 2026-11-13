import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from app.config import configured_secret, settings

logger = logging.getLogger("nexsafe.hosted_inference")
HF_ROUTER = "https://router.huggingface.co/hf-inference/models"
MAX_DETECTIONS = 200


class HostedInferenceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def hosted_provider_status() -> dict[str, Any]:
    selected = settings.inference_provider == "huggingface"
    token_configured = configured_secret(settings.hf_inference_token)
    return {
        "provider": "Hugging Face Inference Providers",
        "provider_id": "huggingface",
        "selected": selected,
        "configured": selected and token_configured,
        "status": "configured" if selected and token_configured else (
            "token_required" if selected else "not_selected"
        ),
        "model": settings.hf_object_detection_model,
        "task": "object-detection",
        "max_video_frames": settings.hf_video_max_frames,
        "model_url": f"https://huggingface.co/{settings.hf_object_detection_model}",
        "provider_url": "https://huggingface.co/docs/inference-providers/tasks/object-detection",
        "privacy_notice": (
            "When hosted inference is enabled, image pixels or sampled video frames "
            "are sent to Hugging Face for inference and are not saved by NexSafe."
        ),
        "limitations": (
            "Generic COCO object detection only; this model does not detect or "
            "confirm accidents, and its confidence is not an accident-risk score."
        ),
    }


def _normalize_detections(payload: Any, width: int, height: int) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise HostedInferenceError("Hosted provider returned an unsupported response.", 502)

    detections = []
    for item in payload[:MAX_DETECTIONS]:
        if not isinstance(item, dict):
            raise HostedInferenceError("Hosted provider returned an invalid detection.", 502)
        box = item.get("box")
        label = item.get("label")
        score = item.get("score")
        if not isinstance(box, dict) or not isinstance(label, str):
            raise HostedInferenceError("Hosted provider returned an invalid detection.", 502)
        try:
            confidence = float(score)
            coordinates = [
                float(box[name])
                for name in ("xmin", "ymin", "xmax", "ymax")
            ]
        except (TypeError, ValueError, KeyError) as exc:
            raise HostedInferenceError(
                "Hosted provider returned invalid detection coordinates.", 502
            ) from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise HostedInferenceError("Hosted provider returned an invalid confidence.", 502)
        if not all(math.isfinite(value) for value in coordinates):
            raise HostedInferenceError("Hosted provider returned invalid coordinates.", 502)

        xmin, ymin, xmax, ymax = coordinates
        xmin = min(max(xmin, 0), width)
        xmax = min(max(xmax, 0), width)
        ymin = min(max(ymin, 0), height)
        ymax = min(max(ymax, 0), height)
        if xmax <= xmin or ymax <= ymin:
            continue
        detections.append({
            "class_id": -1,
            "label": label[:120],
            "confidence": confidence,
            "xyxy": [xmin, ymin, xmax, ymax],
        })
    return detections


class HuggingFaceInferenceProvider:
    @property
    def configured(self) -> bool:
        return (
            settings.inference_provider == "huggingface"
            and configured_secret(settings.hf_inference_token)
        )

    async def detect_image(
        self,
        image_bytes: bytes,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> dict[str, Any]:
        if settings.inference_provider != "huggingface":
            raise HostedInferenceError("Hugging Face inference is not the selected provider.", 503)
        if not configured_secret(settings.hf_inference_token):
            raise HostedInferenceError(
                "Hosted inference is selected but HF_INFERENCE_TOKEN is not configured.",
                503,
            )

        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HostedInferenceError("Uploaded file is not a readable image.", 422)
        height, width = image.shape[:2]
        url = f"{HF_ROUTER}/{settings.hf_object_detection_model}"
        headers = {
            "Authorization": f"Bearer {settings.hf_inference_token.get_secret_value()}",
            "Content-Type": "application/octet-stream",
            "Accept": "application/json",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(45, connect=10),
                transport=transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, headers=headers, content=image_bytes)
        except httpx.TimeoutException as exc:
            logger.warning("Hosted inference timed out provider=huggingface")
            raise HostedInferenceError(
                "Hugging Face inference timed out; retry later.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Hosted inference request failed provider=huggingface error_type=%s",
                type(exc).__name__,
            )
            raise HostedInferenceError(
                "Hugging Face inference could not be reached.",
                502,
            ) from exc

        if response.status_code in {401, 403}:
            raise HostedInferenceError(
                "Hugging Face rejected the token. Check its Inference Providers permission.",
                503,
            )
        if response.status_code == 402:
            raise HostedInferenceError(
                "Hugging Face reports that hosted inference credits are unavailable.",
                503,
            )
        if response.status_code == 429:
            raise HostedInferenceError(
                "Hugging Face rate limit reached. Retry after the provider limit resets.",
                429,
            )
        if response.status_code == 503:
            raise HostedInferenceError(
                "The selected Hugging Face model is loading or temporarily unavailable.",
                503,
            )
        if response.is_error:
            logger.warning(
                "Hosted inference returned provider HTTP status=%d",
                response.status_code,
            )
            raise HostedInferenceError(
                f"Hugging Face inference failed (HTTP {response.status_code}).",
                502,
            )
        try:
            detections = _normalize_detections(response.json(), width, height)
        except ValueError as exc:
            raise HostedInferenceError(
                "Hugging Face returned invalid JSON.",
                502,
            ) from exc
        return {
            "detections": detections,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "image_dimensions": {"width": width, "height": height},
            "provider": "Hugging Face Inference Providers",
            "provider_id": "huggingface",
            "model": settings.hf_object_detection_model,
            "task": "object-detection",
            "prediction_type": "object_detection",
            "confirmed_accident": False,
            "notice": (
                "Generic object detections only. This model does not classify "
                "accidents or estimate accident risk."
            ),
        }

    async def detect_video(
        self,
        path: str | Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> dict[str, Any]:
        frame_count, source_fps, dimensions, frames = await asyncio.to_thread(
            _sample_video_frames,
            path,
            settings.hf_video_max_frames,
        )

        if not frames:
            raise HostedInferenceError("No readable video frames were sampled.", 422)

        results = []
        for index, frame_bytes in frames:
            result = await self.detect_image(frame_bytes, transport=transport)
            results.append((index, result))
        all_detections = [
            {"frame": index, **detection}
            for index, result in results
            for detection in result["detections"]
        ]
        return {
            "frames_processed": len(results),
            "source_frames_total": frame_count,
            "frames_sampled": len(results),
            "media_dimensions": dimensions,
            "source_fps": source_fps if math.isfinite(source_fps) and source_fps > 0 else None,
            "inference_latency_ms_mean": sum(
                result["latency_ms"] for _, result in results
            ) / len(results),
            "detections": all_detections,
            "risk_predictions": [],
            "model": settings.hf_object_detection_model,
            "provider": "Hugging Face Inference Providers",
            "provider_id": "huggingface",
            "task": "frame-sampled-object-detection",
            "tracking": None,
            "notice": (
                f"Frame-sampled object detection: {len(results)} of {frame_count} "
                "video frames sent to Hugging Face. This is not continuous video "
                "analysis, object tracking, an accident classifier, or an accident alert."
            ),
            "confirmed_accident": False,
        }


def _sample_video_frames(
    path: str | Path,
    max_frames: int,
) -> tuple[int, float | None, dict[str, int], list[tuple[int, bytes]]]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise HostedInferenceError("Uploaded video could not be opened.", 422)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if frame_count <= 0:
            raise HostedInferenceError(
                "Video frame count is unavailable; hosted frame sampling is disabled.",
                422,
            )
        sample_count = min(frame_count, max_frames)
        indexes = np.linspace(0, frame_count - 1, num=sample_count, dtype=int)
        frames: list[tuple[int, bytes]] = []
        for index in indexes:
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, int(index)):
                raise HostedInferenceError(
                    "Could not seek to a sampled video frame.",
                    422,
                )
            ok, frame = capture.read()
            if not ok:
                continue
            encoded, jpeg = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 90],
            )
            if encoded:
                frames.append((int(index), jpeg.tobytes()))
        normalized_fps = (
            source_fps
            if math.isfinite(source_fps) and source_fps > 0
            else None
        )
        return frame_count, normalized_fps, {"width": width, "height": height}, frames
    finally:
        capture.release()


hosted_inference = HuggingFaceInferenceProvider()
