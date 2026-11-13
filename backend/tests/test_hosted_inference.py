import unittest
from unittest.mock import AsyncMock, patch

import cv2
import httpx
import numpy as np
from pydantic import SecretStr

from app.config import settings
from app.hosted_inference import (
    HostedInferenceError,
    HuggingFaceInferenceProvider,
    hosted_provider_status,
)


class HostedInferenceProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = HuggingFaceInferenceProvider()
        self.old_provider = settings.inference_provider
        self.old_token = settings.hf_inference_token
        self.old_model = settings.hf_object_detection_model
        settings.inference_provider = "huggingface"
        settings.hf_inference_token = SecretStr("unit-test-only-token")
        settings.hf_object_detection_model = "facebook/detr-resnet-50"
        encoded, self.image = cv2.imencode(".png", np.zeros((24, 32, 3), dtype=np.uint8))
        self.assertTrue(encoded)

    async def asyncTearDown(self):
        settings.inference_provider = self.old_provider
        settings.hf_inference_token = self.old_token
        settings.hf_object_detection_model = self.old_model

    async def test_sends_image_to_official_router_and_normalizes_actual_response(self):
        observed = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            observed["url"] = str(request.url)
            observed["authorization"] = request.headers["Authorization"]
            observed["content"] = request.content
            return httpx.Response(
                200,
                json=[{
                    "label": "car",
                    "score": 0.91,
                    "box": {"xmin": 2, "ymin": -3, "xmax": 80, "ymax": 20},
                }],
            )

        result = await self.provider.detect_image(
            self.image.tobytes(),
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(
            observed["url"],
            "https://router.huggingface.co/hf-inference/models/facebook/detr-resnet-50",
        )
        self.assertEqual(observed["authorization"], "Bearer unit-test-only-token")
        self.assertEqual(observed["content"], self.image.tobytes())
        self.assertEqual(result["provider_id"], "huggingface")
        self.assertEqual(result["task"], "object-detection")
        self.assertFalse(result["confirmed_accident"])
        self.assertEqual(result["image_dimensions"], {"width": 32, "height": 24})
        self.assertEqual(result["detections"][0]["label"], "car")
        self.assertEqual(result["detections"][0]["confidence"], 0.91)
        self.assertEqual(result["detections"][0]["xyxy"], [2, 0, 32, 20])
        self.assertNotIn("unit-test-only-token", str(result))

    async def test_rate_limit_has_safe_actionable_error(self):
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "sensitive provider details"})

        with self.assertRaises(HostedInferenceError) as raised:
            await self.provider.detect_image(
                self.image.tobytes(),
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(raised.exception.status_code, 429)
        self.assertNotIn("sensitive provider details", str(raised.exception))

    async def test_invalid_provider_payload_is_not_presented_as_prediction(self):
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "unexpected shape"})

        with self.assertRaises(HostedInferenceError) as raised:
            await self.provider.detect_image(
                self.image.tobytes(),
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("unsupported response", str(raised.exception))

    async def test_unconfigured_token_fails_closed(self):
        settings.hf_inference_token = None
        with self.assertRaises(HostedInferenceError) as raised:
            await self.provider.detect_image(self.image.tobytes())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("HF_INFERENCE_TOKEN", str(raised.exception))

    async def test_video_uses_bounded_samples_and_never_claims_accident_risk(self):
        frame_result = {
            "detections": [{"label": "car", "confidence": 0.9, "xyxy": [1, 2, 20, 18]}],
            "latency_ms": 10,
        }
        sampled_frames = [(0, b"frame-0"), (49, b"frame-49")]
        with (
            patch(
                "app.hosted_inference._sample_video_frames",
                return_value=(
                    50,
                    25.0,
                    {"width": 640, "height": 480},
                    sampled_frames,
                ),
            ) as sample,
            patch.object(
                self.provider,
                "detect_image",
                new=AsyncMock(return_value=frame_result),
            ) as detect,
        ):
            result = await self.provider.detect_video("sample.mp4")

        sample.assert_called_once_with("sample.mp4", settings.hf_video_max_frames)
        self.assertEqual(detect.await_count, 2)
        self.assertEqual(result["frames_sampled"], 2)
        self.assertEqual(result["source_frames_total"], 50)
        self.assertEqual([item["frame"] for item in result["detections"]], [0, 49])
        self.assertEqual(result["risk_predictions"], [])
        self.assertFalse(result["confirmed_accident"])
        self.assertIn("not continuous video", result["notice"])

    def test_status_never_exposes_configured_token(self):
        status = hosted_provider_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["model"], "facebook/detr-resnet-50")
        self.assertNotIn("unit-test-only-token", str(status))
        self.assertIn("does not detect or", status["limitations"])


if __name__ == "__main__":
    unittest.main()
