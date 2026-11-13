import logging
import math
from pathlib import Path
from threading import Lock

from app.config import settings

logger = logging.getLogger("nexsafe.structured-risk")


class StructuredRiskService:
    def __init__(self) -> None:
        self.model = None
        self.classes: list[str] = []
        self.feature_names: list[str] = []
        self.mean: list[float] = []
        self.scale: list[float] = []
        self.metrics: dict | None = None
        self.training_info: dict | None = None
        self.version: str | None = None
        self.device = "cpu"
        self.error: str | None = None
        self.lock = Lock()
        checkpoint_path = settings.road_risk_model_weights
        if not checkpoint_path:
            self.error = "No trained structured risk checkpoint configured"
            logger.warning("Structured risk inference unavailable: %s", self.error)
            return
        path = Path(checkpoint_path)
        if not path.is_file():
            self.error = "Configured structured risk checkpoint is unavailable"
            logger.error("%s", self.error)
            return
        try:
            import torch
            from app.structured_risk_model import RoadRiskMLP

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            checkpoint = torch.load(path, map_location=self.device, weights_only=True)
            classes = checkpoint.get("classes")
            feature_names = checkpoint.get("feature_names")
            mean = checkpoint.get("mean")
            scale = checkpoint.get("scale")
            training_info = checkpoint.get("training_info")
            validation_metrics = checkpoint.get("validation_metrics")
            test_metrics = checkpoint.get("test_metrics")
            if (
                checkpoint.get("format_version") != 1
                or not isinstance(classes, list) or len(classes) < 2
                or not all(isinstance(item, str) and item for item in classes)
                or not isinstance(feature_names, list) or not feature_names
                or not all(isinstance(item, str) and item for item in feature_names)
                or len(set(feature_names)) != len(feature_names)
                or not isinstance(mean, list) or not isinstance(scale, list)
                or len(mean) != len(feature_names) or len(scale) != len(feature_names)
                or not all(isinstance(item, (int, float)) and math.isfinite(item) for item in mean + scale)
                or any(item <= 0 for item in scale)
                or not isinstance(training_info, dict)
                or not training_info.get("dataset_name")
                or not training_info.get("label_definition")
                or not training_info.get("license")
                or not isinstance(validation_metrics, dict)
                or not isinstance(test_metrics, dict)
                or not training_info.get("test_csv_sha256")
            ):
                raise ValueError("Structured checkpoint lacks real data provenance or held-out test metrics")
            model = RoadRiskMLP(len(feature_names), len(classes)).to(self.device)
            model.load_state_dict(checkpoint["state_dict"])
            model.eval()
            self.model = model
            self.classes = classes
            self.feature_names = feature_names
            self.mean = [float(item) for item in mean]
            self.scale = [float(item) for item in scale]
            self.metrics = {"validation": validation_metrics, "test": test_metrics}
            self.training_info = {
                key: value for key, value in training_info.items()
                if not key.endswith("_csv_sha256")
            }
            self.version = str(checkpoint.get("model_version", path.name))
            logger.info("Loaded validated structured risk checkpoint %s", path.name)
        except Exception as exc:
            logger.exception("Structured risk checkpoint could not be loaded")
            self.error = f"Structured risk model unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self.model is not None

    def predict(self, features: dict) -> dict:
        if self.model is None:
            raise RuntimeError("Structured road-risk model unavailable; inference disabled.")
        if set(features) != set(self.feature_names):
            raise ValueError(f"Expected exactly these model feature names: {self.feature_names}")
        values = []
        for name in self.feature_names:
            value = features[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Feature {name!r} must be a finite number")
            values.append((float(value) - self.mean[len(values)]) / self.scale[len(values)])

        import torch

        tensor = torch.tensor([values], dtype=torch.float32, device=self.device)
        with self.lock, torch.inference_mode():
            probabilities = torch.softmax(self.model(tensor), dim=1)[0].cpu().tolist()
        class_probabilities = {
            name: float(probabilities[index]) for index, name in enumerate(self.classes)
        }
        positive_classes = {
            name.strip().casefold()
            for name in settings.road_risk_positive_classes.split(",")
            if name.strip()
        }
        configured_classes = {name.casefold() for name in self.classes}
        positive_classes_match = bool(positive_classes) and positive_classes.issubset(configured_classes)
        risk_score = sum(
            probability for name, probability in class_probabilities.items()
            if name.casefold() in positive_classes
        ) if positive_classes_match else None
        predicted_class = self.classes[max(range(len(probabilities)), key=probabilities.__getitem__)]
        prediction = {
            "prediction_type": "structured_road_risk_model",
            "class": predicted_class,
            "confidence": float(max(probabilities)),
            "risk_score": risk_score,
            "risk_score_status": (
                "available" if risk_score is not None
                else "positive_classes_not_configured" if not positive_classes
                else "positive_classes_do_not_match_checkpoint"
            ),
            "class_probabilities": class_probabilities,
            "model_version": self.version,
            "confirmed_accident": False,
        }
        logger.debug(
            "Structured risk prediction completed: model=%s class=%s confidence=%.4f",
            self.version,
            predicted_class,
            prediction["confidence"],
        )
        return prediction


structured_risk_service = StructuredRiskService()
