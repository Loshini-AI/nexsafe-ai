import logging
import threading
from pathlib import Path

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("nexsafe.temporal")


class TemporalRiskService:
    def __init__(self) -> None:
        self.model = None
        self.classes: list[str] = []
        self.metrics: dict | None = None
        self.test_metrics: dict | None = None
        self.dataset_info: dict | None = None
        self.version: str | None = None
        self.error: str | None = None
        self.lock = threading.Lock()
        self.device = "cpu"
        self.sequence_length = 16
        self.image_size = 112
        self.window_seconds = 4.0
        weights_path = settings.accident_model_weights
        if not weights_path:
            self.error = "No validated temporal accident model configured"
            logger.warning("Temporal accident inference unavailable: %s", self.error)
            return
        path = Path(weights_path)
        if not path.is_file():
            self.error = "Configured temporal model checkpoint is unavailable"
            logger.error("%s", self.error)
            return
        try:
            import torch

            from app.training_model import CNNLSTM

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            checkpoint = torch.load(path, map_location=self.device, weights_only=True)
            classes = checkpoint.get("classes")
            metrics = checkpoint.get("validation_metrics")
            test_metrics = checkpoint.get("test_metrics")
            info = checkpoint.get("training_info")
            if (
                checkpoint.get("format_version") != 1
                or not isinstance(classes, list)
                or len(classes) < 2
                or not all(isinstance(label, str) and label for label in classes)
                or not isinstance(checkpoint.get("state_dict"), dict)
                or not isinstance(metrics, dict)
                or not isinstance(info, dict)
                or not info.get("validation_manifest_sha256")
            ):
                raise ValueError("Checkpoint is missing validated training metadata")
            required_metrics = {
                "accuracy", "macro_precision", "macro_recall", "macro_f1",
                "validation_segments", "per_class",
            }
            if not required_metrics.issubset(metrics) or not info.get("dataset_name"):
                raise ValueError("Checkpoint does not identify its dataset and validation metrics")
            risk_classes = {
                label.strip().lower()
                for label in settings.accident_risk_classes.split(",")
                if label.strip()
            }
            if not risk_classes.intersection(label.strip().lower() for label in classes):
                raise ValueError("Configured risk classes do not match the checkpoint labels")
            self.sequence_length = int(checkpoint.get("sequence_length", 16))
            self.image_size = int(checkpoint.get("image_size", 112))
            self.window_seconds = float(checkpoint.get("window_seconds", 4.0))
            if self.sequence_length < 2 or self.image_size < 32 or self.window_seconds <= 0:
                raise ValueError("Checkpoint temporal dimensions are invalid")
            self.model = CNNLSTM(len(classes)).to(self.device)
            self.model.load_state_dict(checkpoint["state_dict"])
            self.model.eval()
            self.classes = classes
            self.metrics = metrics
            self.test_metrics = test_metrics if isinstance(test_metrics, dict) else None
            self.dataset_info = {
                key: value for key, value in info.items()
                if key not in {
                    "train_manifest_sha256", "validation_manifest_sha256",
                    "test_manifest_sha256",
                }
            }
            self.version = str(checkpoint.get("model_version", path.name))
            logger.info("Loaded validated temporal model checkpoint %s", path.name)
        except Exception as exc:
            logger.exception("Temporal model checkpoint could not be loaded")
            self.error = f"Temporal model unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self.model is not None

    def predict(self, frames: list[np.ndarray]) -> dict | None:
        if not self.model or len(frames) < self.sequence_length:
            return None
        import torch

        selected = frames[-self.sequence_length :]
        images = []
        for frame in selected:
            resized = cv2.resize(frame, (self.image_size, self.image_size), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            images.append(rgb)
        array = np.stack(images).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(0, 3, 1, 2).unsqueeze(0).to(self.device)
        with self.lock, torch.inference_mode():
            probabilities = torch.softmax(self.model(tensor), dim=1)[0].cpu().tolist()
        predicted_index = int(np.argmax(probabilities))
        dangerous = {
            label.strip().lower()
            for label in settings.accident_risk_classes.split(",")
            if label.strip()
        }
        risk_score = sum(
            probability
            for label, probability in zip(self.classes, probabilities)
            if label.strip().lower() in dangerous
        )
        prediction = {
            "class": self.classes[predicted_index],
            "confidence": float(probabilities[predicted_index]),
            "risk_score": float(risk_score),
            "model_version": self.version,
            "prediction_type": "temporal_model_prediction",
            "sequence_frames": len(selected),
        }
        logger.debug(
            "Temporal prediction completed: model=%s class=%s confidence=%.4f risk_score=%.4f",
            self.version,
            prediction["class"],
            prediction["confidence"],
            prediction["risk_score"],
        )
        return prediction


temporal_risk_service = TemporalRiskService()
