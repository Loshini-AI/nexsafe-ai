import json
import struct
import tempfile
import unittest
from pathlib import Path

from training.prepare_uvh26 import CLASS_NAMES, _convert_split


class PrepareUVH26Tests(unittest.TestCase):
    def test_uses_the_publisher_taxonomy(self):
        self.assertIn("Others", CLASS_NAMES)
        self.assertNotIn("Other", CLASS_NAMES)

    def test_converts_coco_box_without_inventing_classes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root = root / "source"
            image_root.mkdir()
            png_header = (
                b"\x89PNG\r\n\x1a\n"
                + b"\x00\x00\x00\x0dIHDR"
                + struct.pack(">II", 100, 50)
            )
            (image_root / "frame.png").write_bytes(png_header)
            annotation_file = root / "annotations.json"
            annotation_file.write_text(
                json.dumps({
                    "categories": [
                        {"id": index + 1, "name": name}
                        for index, name in enumerate(CLASS_NAMES)
                    ],
                    "images": [{"id": 8, "file_name": "frame.png", "width": 100, "height": 50}],
                    "annotations": [
                        {"id": 1, "image_id": 8, "category_id": 8, "bbox": [10, 5, 20, 15]}
                    ],
                }),
                encoding="utf-8",
            )
            report = _convert_split(
                split_name="train",
                image_root=image_root,
                annotation_file=annotation_file,
                output_root=root / "prepared",
                link_mode="copy",
            )
            label = (root / "prepared" / "labels" / "train" / "frame.txt").read_text(
                encoding="utf-8"
            )
            self.assertEqual(report["images"], 1)
            self.assertEqual(report["annotations"], 1)
            self.assertEqual(label.strip(), "7 0.20000000 0.25000000 0.20000000 0.30000000")
            self.assertNotIn("Pedestrian", CLASS_NAMES)

    def test_rejects_image_dimensions_that_disagree_with_coco(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root = root / "source"
            image_root.mkdir()
            png_header = (
                b"\x89PNG\r\n\x1a\n"
                + b"\x00\x00\x00\x0dIHDR"
                + struct.pack(">II", 99, 50)
            )
            (image_root / "frame.png").write_bytes(png_header)
            annotation_file = root / "annotations.json"
            annotation_file.write_text(
                json.dumps({
                    "categories": [
                        {"id": index + 1, "name": name}
                        for index, name in enumerate(CLASS_NAMES)
                    ],
                    "images": [{"id": 8, "file_name": "frame.png", "width": 100, "height": 50}],
                    "annotations": [],
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Image dimensions disagree"):
                _convert_split(
                    split_name="train",
                    image_root=image_root,
                    annotation_file=annotation_file,
                    output_root=root / "prepared",
                    link_mode="copy",
                )

    def test_rejects_unverified_taxonomy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            annotation_file = root / "annotations.json"
            annotation_file.write_text(
                json.dumps({"categories": [{"id": 1, "name": "Pedestrian"}],
                            "images": [], "annotations": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "taxonomy changed"):
                from training.prepare_uvh26 import _read_coco

                _read_coco(annotation_file)


if __name__ == "__main__":
    unittest.main()
