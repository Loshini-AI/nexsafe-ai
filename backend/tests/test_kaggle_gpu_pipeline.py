import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from training.audit_datasets import audit_uvh26
from training.kaggle_gpu_pipeline import (
    _redact_secrets,
    _read_training_metrics,
    _subset_cache_path,
    run_structured_if_prepared,
    run_temporal_if_prepared,
)
from training.prepare_uvh26 import CLASS_NAMES


class KaggleGpuPipelineTests(unittest.TestCase):
    def test_redacts_api_credentials(self):
        message = _redact_secrets(
            "username=operator key=secret-token",
            "operator",
            "secret-token",
        )
        self.assertEqual(message, "username=[REDACTED] key=[REDACTED]")

    def test_subset_cache_is_resumable_per_exact_selection(self):
        root = Path("cache")
        first = _subset_cache_path(root, 400, 100, 42)
        same_selection = _subset_cache_path(root, 400, 100, 42)
        different_selection = _subset_cache_path(root, 500, 100, 42)

        self.assertEqual(first, same_selection)
        self.assertNotEqual(first, different_selection)
        self.assertTrue(first.name.startswith("uvh26-"))

    def test_reads_real_training_losses_from_yolo_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            results_file = Path(temporary) / "results.csv"
            results_file.write_text(
                "epoch,train/box_loss,train/cls_loss\n0,1.25,2.5\n1,0.75,1.5\n",
                encoding="utf-8",
            )
            metrics = _read_training_metrics(results_file)

        self.assertEqual(metrics["epochs_recorded"], 2)
        self.assertEqual(metrics["last_epoch"], 1)
        self.assertEqual(
            metrics["last_epoch_training_losses"],
            {"train/box_loss": 0.75, "train/cls_loss": 1.5},
        )

    def test_temporal_training_requires_owner_supplied_splits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(
                "os.environ",
                {"NEXSAFE_TEMPORAL_MANIFEST_ROOT": str(root)},
            ):
                report = run_temporal_if_prepared(root / "output")
        self.assertEqual(report["status"], "blocked")
        self.assertIn("owner-annotated", report["reason"])

    def test_structured_training_requires_observed_splits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(
                "os.environ",
                {"NEXSAFE_ROAD_RISK_CSV_ROOT": str(root)},
            ):
                report = run_structured_if_prepared(root / "output")
        self.assertEqual(report["status"], "blocked")
        self.assertIn("road-risk CSVs attached", report["reason"])

    def test_partial_audit_reports_annotation_dimension_mismatches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for split, folder_name, label in (
                ("train", "UVH-26-Train", "Train"),
                ("val", "UVH-26-Val", "Val"),
            ):
                folder = root / folder_name
                image_root = folder / "data"
                image_root.mkdir(parents=True)
                actual_width = 99 if split == "train" else 100
                header = (
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\x0dIHDR"
                    + struct.pack(">II", actual_width, 50)
                )
                (image_root / "frame.png").write_bytes(header)
                annotation = {
                    "categories": [
                        {"id": index + 1, "name": name}
                        for index, name in enumerate(CLASS_NAMES)
                    ],
                    "images": [
                        {"id": 1, "file_name": "frame.png", "width": 100, "height": 50}
                    ],
                    "annotations": [],
                }
                (folder / f"UVH-26-MV-{label}.json").write_text(
                    json.dumps(annotation),
                    encoding="utf-8",
                )

            report = audit_uvh26(root, "MV", allow_incomplete=True)

        self.assertEqual(report["audit_status"], "incomplete")
        self.assertEqual(len(report["splits"][0]["image_dimension_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
