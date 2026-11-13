import json
import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.dataset_status import load_dataset_status


class DatasetStatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.previous_audit_path = settings.dataset_audit_path
        self.previous_catalog_path = settings.dataset_catalog_path
        settings.dataset_audit_path = str(self.root / "audit.json")
        settings.dataset_catalog_path = str(self.root / "catalog.json")

    def tearDown(self):
        settings.dataset_audit_path = self.previous_audit_path
        settings.dataset_catalog_path = self.previous_catalog_path
        self.temporary_directory.cleanup()

    def test_reports_actual_incomplete_split_counts_and_source_tasks(self):
        Path(settings.dataset_audit_path).write_text(
            json.dumps({
                "generated_at": "2026-11-08T00:00:00+00:00",
                "datasets": {
                    "uvh26": {
                        "audit_status": "incomplete",
                        "license": "CC BY 4.0",
                        "revision": "pinned-revision",
                        "splits": [{
                            "split": "train",
                            "audit_status": "incomplete",
                            "png_files": 12,
                            "images": 20,
                            "missing_images": 8,
                            "annotation_count": 45,
                            "image_bytes": 1000,
                            "image_dimension_mismatches": [{"file": "bad.png"}],
                        }],
                    },
                },
            }),
            encoding="utf-8",
        )
        Path(settings.dataset_catalog_path).write_text(
            json.dumps({
                "sources": [{
                    "id": "uvh-26",
                    "name": "UVH-26",
                    "url": "https://example.invalid/uvh26",
                    "license": "CC BY 4.0",
                    "supported_tasks": ["vehicle_detection"],
                    "not_supported": ["temporal_accident_detection"],
                }],
            }),
            encoding="utf-8",
        )

        result = load_dataset_status()

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["dataset"]["supported_tasks"], ["vehicle_detection"])
        self.assertEqual(result["splits"][0]["available_images"], 12)
        self.assertEqual(result["splits"][0]["missing_images"], 8)
        self.assertEqual(result["splits"][0]["dimension_mismatches"], 1)

    def test_missing_audit_is_reported_as_unavailable(self):
        result = load_dataset_status()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["dataset"])

    def test_invalid_audit_is_reported_as_error(self):
        Path(settings.dataset_audit_path).write_text("{", encoding="utf-8")
        Path(settings.dataset_catalog_path).write_text('{"sources":[]}', encoding="utf-8")

        result = load_dataset_status()

        self.assertEqual(result["status"], "error")
        self.assertIn("JSONDecodeError", result["message"])


if __name__ == "__main__":
    unittest.main()
