import argparse
import hashlib
import json
import os
import struct
from collections import Counter
from pathlib import Path
from typing import Any


CLASS_NAMES = [
    "Hatchback",
    "Sedan",
    "SUV",
    "MUV",
    "Bus",
    "Truck",
    "Three-wheeler",
    "Two-wheeler",
    "LCV",
    "Mini-bus",
    "Tempo-traveller",
    "Bicycle",
    "Van",
    "Others",
]


def _image_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.casefold() == ".png":
        with path.open("rb") as image:
            header = image.read(24)
        if (
            len(header) != 24
            or header[:8] != b"\x89PNG\r\n\x1a\n"
            or header[12:16] != b"IHDR"
        ):
            raise ValueError(f"Invalid PNG signature/IHDR: {path}")
        width, height = struct.unpack(">II", header[16:24])
    else:
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Could not read dataset image: {path}")
        height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image dimensions: {path}")
    return width, height


def _image_index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for image_path in root.rglob("*"):
        if image_path.is_file() and image_path.suffix.casefold() in {".jpg", ".jpeg", ".png"}:
            if image_path.name in result:
                raise ValueError(f"Duplicate image basename makes COCO paths ambiguous: {image_path.name}")
            result[image_path.name] = image_path
    if not result:
        raise FileNotFoundError(f"No extracted dataset images found under {root}")
    return result


def _read_coco(path: Path) -> tuple[dict[str, Any], dict[int, int]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected COCO JSON object: {path}")
    categories = data.get("categories")
    images = data.get("images")
    annotations = data.get("annotations")
    if not all(isinstance(value, list) for value in (categories, images, annotations)):
        raise ValueError(f"COCO JSON requires categories, images, and annotations: {path}")
    actual_categories = {item["name"] for item in categories if isinstance(item, dict) and "name" in item}
    if actual_categories != set(CLASS_NAMES):
        raise ValueError(
            f"UVH category taxonomy changed: expected {CLASS_NAMES!r}, got {sorted(actual_categories)!r}"
        )
    category_ids = {item["id"]: CLASS_NAMES.index(item["name"]) for item in categories}
    if len(category_ids) != len(categories):
        raise ValueError(f"Duplicate COCO category ID in {path}")
    return data, category_ids


def _convert_split(
    *,
    split_name: str,
    image_root: Path,
    annotation_file: Path,
    output_root: Path,
    link_mode: str,
) -> dict[str, Any]:
    coco, category_map = _read_coco(annotation_file)
    indexed_images = _image_index(image_root)
    images = coco["images"]
    annotations = coco["annotations"]
    image_by_id: dict[int, dict[str, Any]] = {}
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("id"), int):
            raise ValueError(f"Invalid image entry in {annotation_file}")
        if image["id"] in image_by_id:
            raise ValueError(f"Duplicate COCO image ID: {image['id']}")
        image_by_id[image["id"]] = image

    labels_by_image: dict[int, list[str]] = {image_id: [] for image_id in image_by_id}
    instances_by_class: Counter[str] = Counter()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise ValueError(f"Invalid annotation entry in {annotation_file}")
        image_id = annotation.get("image_id")
        category_id = annotation.get("category_id")
        bbox = annotation.get("bbox")
        if image_id not in image_by_id or category_id not in category_map:
            raise ValueError(f"Annotation refers to unknown image/category in {annotation_file}")
        image = image_by_id[image_id]
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
        ):
            raise ValueError(f"Invalid COCO bbox in {annotation_file}")
        x, y, width, height = (float(value) for value in bbox)
        image_width, image_height = float(image["width"]), float(image["height"])
        if image_width <= 0 or image_height <= 0 or width <= 0 or height <= 0:
            raise ValueError(f"Non-positive image or bbox dimensions in {annotation_file}")
        x1, y1 = max(0.0, x), max(0.0, y)
        x2, y2 = min(image_width, x + width), min(image_height, y + height)
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Bounding box lies outside its image in {annotation_file}")
        class_index = category_map[category_id]
        center_x = ((x1 + x2) / 2) / image_width
        center_y = ((y1 + y2) / 2) / image_height
        normalized_width = (x2 - x1) / image_width
        normalized_height = (y2 - y1) / image_height
        labels_by_image[image_id].append(
            f"{class_index} {center_x:.8f} {center_y:.8f} {normalized_width:.8f} {normalized_height:.8f}"
        )
        instances_by_class[CLASS_NAMES[class_index]] += 1

    images_out = output_root / "images" / split_name
    labels_out = output_root / "labels" / split_name
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for image_id, image in image_by_id.items():
        file_name = Path(str(image.get("file_name", ""))).name
        source = indexed_images.get(file_name)
        if source is None:
            missing.append(file_name)
            continue
        actual_width, actual_height = _image_dimensions(source)
        expected_width, expected_height = int(image["width"]), int(image["height"])
        if (actual_width, actual_height) != (expected_width, expected_height):
            raise ValueError(
                f"Image dimensions disagree with COCO metadata for {file_name}: "
                f"image is {actual_width}x{actual_height}, annotation says "
                f"{expected_width}x{expected_height}"
            )
        destination = images_out / file_name
        label_file = labels_out / f"{Path(file_name).stem}.txt"
        if destination.exists() or label_file.exists():
            raise FileExistsError(f"Output already contains prepared image/label: {file_name}")
        if link_mode == "hardlink":
            os.link(source, destination)
        else:
            import shutil

            shutil.copy2(source, destination)
        label_file.write_text(
            "\n".join(labels_by_image[image_id]) + ("\n" if labels_by_image[image_id] else ""),
            encoding="utf-8",
        )
    if missing:
        raise FileNotFoundError(f"{len(missing)} COCO images are missing; first missing image: {missing[0]}")
    return {
        "split": split_name,
        "annotation_file": str(annotation_file.resolve()),
        "annotation_sha256": hashlib.sha256(annotation_file.read_bytes()).hexdigest(),
        "images": len(image_by_id),
        "annotations": len(annotations),
        "instances_by_class": dict(sorted(instances_by_class.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert the official UVH-26 COCO splits to YOLO detection format.")
    parser.add_argument("--root", type=Path, required=True, help="Extracted UVH-26 repository directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation-variant", choices=("MV", "ST"), default="MV")
    parser.add_argument("--link-mode", choices=("hardlink", "copy"), default="hardlink")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        parser.error(f"UVH-26 root does not exist: {root}")
    if output.exists() and any(output.iterdir()):
        parser.error(f"Output must be an empty/new directory: {output}")

    results = []
    for split, source_folder, split_label in (
        ("train", "UVH-26-Train", "Train"),
        ("val", "UVH-26-Val", "Val"),
    ):
        folder = root / source_folder
        results.append(
            _convert_split(
                split_name=split,
                image_root=folder / "data",
                annotation_file=folder / f"UVH-26-{args.annotation_variant}-{split_label}.json",
                output_root=output,
                link_mode=args.link_mode,
            )
        )
    dataset_yaml = {
        "path": str(output),
        "train": "images/train",
        "val": "images/val",
        "names": CLASS_NAMES,
    }
    (output / "data.yaml").write_text(json.dumps(dataset_yaml, indent=2), encoding="utf-8")
    (output / "preparation-report.json").write_text(
        json.dumps(
            {
                "dataset": "UVH-26",
                "revision": "59f82c57821e8a54dc40bc1f42e83909dbad0b70",
                "license": "CC BY 4.0",
                "annotation_variant": args.annotation_variant,
                "split_policy": "Publisher-defined 80/20 train/validation; no test split is provided.",
                "link_mode": args.link_mode,
                "classes": CLASS_NAMES,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
