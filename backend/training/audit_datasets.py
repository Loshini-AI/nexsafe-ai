import argparse
import csv
import hashlib
import json
import math
import shutil
import struct
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from training.prepare_uvh26 import CLASS_NAMES

UVH_REVISION = "59f82c57821e8a54dc40bc1f42e83909dbad0b70"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".mpeg", ".mpg"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        header = image.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid PNG signature/IHDR: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid PNG dimensions: {path}")
    return width, height


def audit_uvh26(
    root: Path,
    annotation_variant: str,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    split_results = []
    for split, folder_name, label in (
        ("train", "UVH-26-Train", "Train"),
        ("val", "UVH-26-Val", "Val"),
    ):
        folder = root / folder_name
        image_root = folder / "data"
        annotation_path = folder / f"UVH-26-{annotation_variant}-{label}.json"
        if not allow_incomplete and (not image_root.is_dir() or not annotation_path.is_file()):
            raise FileNotFoundError(f"Missing UVH-26 {split} images or annotation JSON under {folder}")
        if not annotation_path.is_file():
            available_images = list(image_root.rglob("*.png")) if image_root.is_dir() else []
            image_bytes = 0
            for path in available_images:
                png_dimensions(path)
                image_bytes += path.stat().st_size
            split_results.append({
                "split": split,
                "images": None,
                "png_files": len(available_images),
                "image_bytes": image_bytes,
                "image_bytes_sha256": None,
                "annotation_status": "not_downloaded",
                "annotation_count": None,
                "images_with_annotations": None,
                "images_without_annotations": None,
                "instances_by_class": None,
                "annotation_file": str(annotation_path),
                "annotation_file_bytes": None,
                "annotation_file_sha256": None,
                "image_dimensions_verified_from_png_headers": True,
                "bounding_boxes_validated": False,
                "audit_status": "incomplete",
            })
            continue
        with annotation_path.open(encoding="utf-8") as source:
            coco = json.load(source)
        if not all(isinstance(coco.get(key), list) for key in ("images", "annotations", "categories")):
            raise ValueError(f"Invalid COCO structure in {annotation_path}")
        category_names = {
            entry.get("name"): entry.get("id")
            for entry in coco["categories"]
            if isinstance(entry, dict)
        }
        if set(category_names) != set(CLASS_NAMES) or len(category_names) != len(coco["categories"]):
            raise ValueError(f"Unexpected UVH-26 taxonomy in {annotation_path}: {sorted(category_names)}")
        category_ids = {category_id: name for name, category_id in category_names.items()}
        images_by_id = {}
        names_seen: set[str] = set()
        labeled_images: set[int] = set()
        for image in coco["images"]:
            if not isinstance(image, dict) or not isinstance(image.get("id"), int):
                raise ValueError(f"Invalid image entry in {annotation_path}")
            if image["id"] in images_by_id:
                raise ValueError(f"Duplicate COCO image ID {image['id']} in {annotation_path}")
            name = Path(str(image.get("file_name", ""))).name
            if not name or name in names_seen:
                raise ValueError(f"Missing or duplicate COCO image filename {name!r} in {annotation_path}")
            names_seen.add(name)
            images_by_id[image["id"]] = image

        class_instances: Counter[str] = Counter()
        for annotation in coco["annotations"]:
            if not isinstance(annotation, dict):
                raise ValueError(f"Invalid annotation entry in {annotation_path}")
            image_id = annotation.get("image_id")
            category_id = annotation.get("category_id")
            bbox = annotation.get("bbox")
            if image_id not in images_by_id or category_id not in category_ids:
                raise ValueError(f"Annotation references missing image/category in {annotation_path}")
            image = images_by_id[image_id]
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bbox)
            ):
                raise ValueError(f"Invalid bbox in {annotation_path}")
            x, y, width, height = map(float, bbox)
            image_width, image_height = float(image["width"]), float(image["height"])
            if (
                x < 0 or y < 0 or width <= 0 or height <= 0
                or image_width <= 0 or image_height <= 0
                or x + width > image_width + 1
                or y + height > image_height + 1
            ):
                raise ValueError(f"Out-of-image/invalid bbox in {annotation_path}")
            class_instances[category_ids[category_id]] += 1
            labeled_images.add(image_id)

        disk_images: dict[str, Path] = {}
        image_bytes = 0
        dimension_mismatches = []
        for image_path in image_root.rglob("*.png"):
            if image_path.name in disk_images:
                raise ValueError(f"Duplicate image basename on disk: {image_path.name}")
            disk_images[image_path.name] = image_path
            image_bytes += image_path.stat().st_size
        missing_images = sorted(names_seen - disk_images.keys())
        orphan_images = sorted(disk_images.keys() - names_seen)
        if (missing_images or orphan_images) and not allow_incomplete:
            raise ValueError(
                f"UVH-26 {split} files and COCO records differ "
                f"(missing={len(missing_images)}, orphan={len(orphan_images)})"
            )
        checked_images = 0
        for image_id, metadata in images_by_id.items():
            path = disk_images.get(Path(str(metadata["file_name"])).name)
            if path is None:
                continue
            width, height = png_dimensions(path)
            checked_images += 1
            if width != int(metadata["width"]) or height != int(metadata["height"]):
                dimension_mismatches.append({
                    "file": path.name,
                    "annotation_dimensions": [metadata["width"], metadata["height"]],
                    "png_dimensions": [width, height],
                })
        if dimension_mismatches and not allow_incomplete:
            raise ValueError(f"{len(dimension_mismatches)} UVH-26 image dimensions disagree with COCO")
        split_results.append({
            "split": split,
            "images": len(images_by_id),
            "png_files": len(disk_images),
            "missing_images": len(missing_images),
            "orphan_images": len(orphan_images),
            "image_bytes": image_bytes,
            "image_bytes_sha256": None,
            "annotation_status": "verified",
            "annotation_count": len(coco["annotations"]),
            "images_with_annotations": len(labeled_images),
            "images_without_annotations": len(images_by_id) - len(labeled_images),
            "instances_by_class": dict(sorted(class_instances.items())),
            "annotation_file": str(annotation_path),
            "annotation_file_bytes": annotation_path.stat().st_size,
            "annotation_file_sha256": sha256_file(annotation_path),
            "image_dimensions_verified_from_png_headers": checked_images == len(disk_images),
            "image_dimensions_checked_count": checked_images,
            "image_dimension_mismatches": dimension_mismatches,
            "bounding_boxes_validated": True,
            "audit_status": (
                "passed"
                if not missing_images and not orphan_images and not dimension_mismatches
                else "incomplete"
            ),
        })
    return {
        "dataset": "UVH-26",
        "source": "https://huggingface.co/datasets/iisc-aim/UVH-26",
        "revision": UVH_REVISION,
        "license": "CC BY 4.0",
        "annotation_variant": annotation_variant,
        "split_policy": "Publisher-defined train/validation only; source has no held-out test split.",
        "sha256_for_each_image": False,
        "splits": split_results,
        "audit_status": (
            "passed"
            if all(result["audit_status"] == "passed" for result in split_results)
            else "incomplete"
        ),
    }


def audit_videos(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"audit_status": "not_available", "message": f"Dataset root not found: {root}"}
    video_paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
    )
    metadata_paths = sorted(
        path for path in root.rglob("*.csv")
        if "metadata" in path.name.casefold() or "label" in path.name.casefold()
    )
    metadata_reports = []
    for path in metadata_paths:
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            rows = list(reader)
        headers = reader.fieldnames or []
        label_headers = [
            header for header in headers
            if any(key in header.casefold() for key in ("label", "class", "type", "collision", "accident"))
        ]
        label_values = {
            header: dict(Counter(
                (row.get(header) or "").strip()
                for row in rows
                if (row.get(header) or "").strip()
            ))
            for header in label_headers
        }
        metadata_reports.append({
            "file": str(path),
            "rows": len(rows),
            "columns": headers,
            "potential_label_columns": label_headers,
            "observed_values_only": label_values,
            "file_sha256": sha256_file(path),
        })
    probe = shutil.which("ffprobe")
    probe_status = "unavailable"
    video_metadata = []
    probe_errors = []
    if probe:
        probe_status = "passed"
        for path in video_paths:
            result = subprocess.run(
                [
                    probe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames,duration",
                    "-of", "json", str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode:
                probe_errors.append({"file": str(path), "error": result.stderr[-500:]})
                continue
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            if not streams:
                probe_errors.append({"file": str(path), "error": "No video stream"})
                continue
            stream = streams[0]
            video_metadata.append({
                "file": str(path),
                "bytes": path.stat().st_size,
                "codec": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "frame_rate": stream.get("avg_frame_rate"),
                "frame_count": stream.get("nb_frames"),
                "duration_seconds": stream.get("duration"),
            })
        if probe_errors:
            probe_status = "failed"
    return {
        "root": str(root),
        "video_file_count": len(video_paths),
        "metadata_csv_files": metadata_reports,
        "video_metadata_probe": {
            "tool": "ffprobe",
            "status": probe_status,
            "probed": len(video_metadata),
            "errors": probe_errors,
            "video_records": video_metadata,
        },
        "audit_status": (
            "passed"
            if video_paths and metadata_reports and probe_status == "passed" and not probe_errors
            else "incomplete"
        ),
        "interpretation_note": (
            "CSV values are reported as observed only; this audit does not infer "
            "accident negatives or remap labels to collision classes."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit locally downloaded UVH-26 and ACCIDENT files without relabeling.")
    parser.add_argument("--uvh26-root", type=Path)
    parser.add_argument("--accident-root", type=Path)
    parser.add_argument("--annotation-variant", choices=("MV", "ST"), default="MV")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Report available files and validation gaps without claiming a complete dataset audit.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": {},
    }
    if args.uvh26_root:
        report["datasets"]["uvh26"] = audit_uvh26(
            args.uvh26_root.resolve(),
            args.annotation_variant,
            allow_incomplete=args.allow_incomplete,
        )
    if args.accident_root:
        report["datasets"]["accident"] = audit_videos(args.accident_root.resolve())
    if not report["datasets"]:
        parser.error("Provide at least one of --uvh26-root or --accident-root")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(output), "datasets": report["datasets"]}, indent=2))


if __name__ == "__main__":
    main()
