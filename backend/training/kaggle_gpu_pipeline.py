import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from training.prepare_uvh26 import CLASS_NAMES as UVH_CLASSES

UVH_REPO = "iisc-aim/UVH-26"
UVH_REVISION = "59f82c57821e8a54dc40bc1f42e83909dbad0b70"
ACCIDENT_SLUG = "picekl/accident"
ACCIDENT_LICENSE = "CC BY-NC-SA 4.0"
ACCIDENT_BYTES = 20_158_641_093


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redact_secrets(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def _read_coco(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        data = json.load(source)
    categories = data.get("categories")
    if not isinstance(categories, list):
        raise ValueError(f"Invalid COCO categories: {path}")
    names = {item["name"] for item in categories if isinstance(item, dict) and "name" in item}
    if names != set(UVH_CLASSES):
        raise ValueError(f"UVH taxonomy differs from verified classes: {sorted(names)}")
    return data


def _choose_image_ids(coco: dict, count: int, seed: int) -> list[int]:
    records = coco.get("images")
    if not isinstance(records, list) or not records:
        raise ValueError("COCO split has no images")
    image_ids = {entry["id"] for entry in records}
    if len(image_ids) != len(records):
        raise ValueError("COCO split has duplicate image IDs")
    target = min(count, len(records))
    category_images: dict[int, list[int]] = defaultdict(list)
    for annotation in coco.get("annotations", []):
        if annotation.get("image_id") in image_ids:
            category_images[annotation["category_id"]].append(annotation["image_id"])
    rng = random.Random(seed)
    selected: list[int] = []
    selected_set: set[int] = set()
    for category_id in sorted(category_images):
        options = sorted(set(category_images[category_id]))
        rng.shuffle(options)
        candidate = next((image_id for image_id in options if image_id not in selected_set), None)
        if candidate is not None and len(selected) < target:
            selected.append(candidate)
            selected_set.add(candidate)
    remaining = sorted(image_ids - selected_set)
    rng.shuffle(remaining)
    selected.extend(remaining[: target - len(selected)])
    if len(selected) != target:
        raise RuntimeError("Could not construct deterministic image subset")
    return selected


def _subset_cache_path(cache_root: Path, train_count: int, val_count: int, seed: int) -> Path:
    selection = {
        "revision": UVH_REVISION,
        "annotation_variant": "MV",
        "train_images": train_count,
        "validation_images": val_count,
        "seed": seed,
    }
    fingerprint = hashlib.sha256(
        json.dumps(selection, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return cache_root / f"uvh26-{fingerprint}"


def _read_training_metrics(results_file: Path) -> dict:
    import csv

    with results_file.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise RuntimeError(f"YOLO training history is empty: {results_file}")
    final_row = {str(key).strip(): value for key, value in rows[-1].items()}
    training_losses = {
        key: float(value)
        for key, value in final_row.items()
        if key.startswith("train/") and value not in (None, "")
    }
    if not training_losses:
        raise RuntimeError(f"YOLO training history has no training loss columns: {results_file}")
    return {
        "epochs_recorded": len(rows),
        "last_epoch": int(float(final_row["epoch"])),
        "last_epoch_training_losses": training_losses,
    }


def _convert_split(
    split: str,
    coco: dict,
    selected_ids: set[int],
    repository_paths: dict[str, str],
    source_root: Path,
    output_root: Path,
    image_size_reader,
) -> dict:
    split_label = "Train" if split == "train" else "Val"
    split_prefix = f"UVH-26-{split_label}"
    images_by_id = {entry["id"]: entry for entry in coco["images"] if entry["id"] in selected_ids}
    if len(images_by_id) != len(selected_ids):
        raise ValueError(f"Selected {split} image IDs are missing in its COCO annotation")
    labels: dict[int, list[str]] = {image_id: [] for image_id in selected_ids}
    instances: dict[str, int] = {name: 0 for name in UVH_CLASSES}
    category_name = {item["id"]: item["name"] for item in coco["categories"]}
    for annotation in coco["annotations"]:
        image_id = annotation.get("image_id")
        if image_id not in selected_ids:
            continue
        image = images_by_id[image_id]
        category = category_name.get(annotation.get("category_id"))
        bbox = annotation.get("bbox")
        if category not in UVH_CLASSES or not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("Invalid source COCO category or box")
        x, y, width, height = (float(value) for value in bbox)
        source_width, source_height = float(image["width"]), float(image["height"])
        if (
            source_width <= 0 or source_height <= 0 or width <= 0 or height <= 0
            or x < 0 or y < 0 or x + width > source_width + 1
            or y + height > source_height + 1
        ):
            raise ValueError(f"Invalid source box in image ID {image_id}")
        index = UVH_CLASSES.index(category)
        labels[image_id].append(
            f"{index} {(x + width / 2) / source_width:.8f} "
            f"{(y + height / 2) / source_height:.8f} "
            f"{width / source_width:.8f} {height / source_height:.8f}"
        )
        instances[category] += 1

    image_out = output_root / "images" / split
    label_out = output_root / "labels" / split
    image_out.mkdir(parents=True, exist_ok=True)
    label_out.mkdir(parents=True, exist_ok=True)
    image_bytes = 0
    annotated_images = 0
    for image_id, metadata in images_by_id.items():
        basename = PurePosixPath(str(metadata["file_name"])).name
        repository_path = repository_paths.get(basename)
        if repository_path is None:
            raise FileNotFoundError(f"UVH image missing from pinned repository listing: {basename}")
        if not repository_path.startswith(f"{split_prefix}/data/"):
            raise ValueError(f"Image maps to the wrong publisher split: {repository_path}")
        source = source_root / repository_path
        if not source.is_file():
            raise FileNotFoundError(f"UVH sample download missing: {source}")
        width, height = image_size_reader(str(source))
        if width is None or height is None or width != metadata["width"] or height != metadata["height"]:
            raise ValueError(f"Downloaded PNG dimensions do not match COCO metadata: {basename}")
        destination = image_out / basename
        if destination.exists():
            raise FileExistsError(f"Duplicate image in prepared subset: {basename}")
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        image_bytes += destination.stat().st_size
        label_file = label_out / f"{Path(basename).stem}.txt"
        label_file.write_text(
            "\n".join(labels[image_id]) + ("\n" if labels[image_id] else ""),
            encoding="utf-8",
        )
        annotated_images += bool(labels[image_id])
    return {
        "images": len(images_by_id),
        "images_with_annotations": annotated_images,
        "image_bytes": image_bytes,
        "instances_by_class": instances,
    }


def train_detector(output_root: Path) -> dict:
    import torch
    import yaml
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    from ultralytics import YOLO
    import cv2

    if not torch.cuda.is_available():
        raise RuntimeError("Kaggle GPU is not active. Select a GPU accelerator and restart the session.")
    if os.environ.get("NEXSAFE_CONFIRM_ULTRALYTICS_LICENSE_REVIEWED") != "1":
        raise RuntimeError(
            "Review Ultralytics YOLO licensing for your deployment, then set "
            "NEXSAFE_CONFIRM_ULTRALYTICS_LICENSE_REVIEWED=1 in notebook config."
        )
    train_count = int(os.environ.get("NEXSAFE_MAX_TRAIN_IMAGES", "400"))
    val_count = int(os.environ.get("NEXSAFE_MAX_VAL_IMAGES", "100"))
    epochs = int(os.environ.get("NEXSAFE_EPOCHS", "5"))
    batch = int(os.environ.get("NEXSAFE_BATCH", "4"))
    image_size = int(os.environ.get("NEXSAFE_IMAGE_SIZE", "640"))
    seed = int(os.environ.get("NEXSAFE_SEED", "42"))
    if min(train_count, val_count, epochs, batch, image_size) <= 0:
        raise ValueError("Training configuration values must be positive")

    api = HfApi()
    repo_files = api.list_repo_files(
        repo_id=UVH_REPO,
        repo_type="dataset",
        revision=UVH_REVISION,
    )
    image_paths = {}
    for path in repo_files:
        if "/data/" in path and path.casefold().endswith(".png"):
            basename = PurePosixPath(path).name
            if basename in image_paths:
                raise ValueError(f"UVH repository contains ambiguous image basename {basename}")
            image_paths[basename] = path
    if not image_paths:
        raise RuntimeError("No UVH-26 images were listed at the pinned revision")

    prepared = output_root / "uvh26_yolo_subset"
    cache_base = Path(os.environ.get(
        "NEXSAFE_DATA_CACHE",
        "/kaggle/working/nexsafe_training/cache",
    ))
    source_root = _subset_cache_path(cache_base, train_count, val_count, seed)
    source_root.mkdir(parents=True, exist_ok=True)
    prepared.mkdir(parents=True, exist_ok=False)
    selected: dict[str, dict] = {}
    split_reports = {}
    for split, source_folder, source_split, requested_count in (
        ("train", "UVH-26-Train", "Train", train_count),
        ("val", "UVH-26-Val", "Val", val_count),
    ):
        annotation_name = f"{source_folder}/UVH-26-MV-{source_split}.json"
        annotation_path = Path(hf_hub_download(
            repo_id=UVH_REPO,
            repo_type="dataset",
            revision=UVH_REVISION,
            filename=annotation_name,
            local_dir=str(source_root),
        ))
        coco = _read_coco(annotation_path)
        selected_ids = _choose_image_ids(coco, requested_count, seed + (split == "val"))
        selected[split] = {
            "annotation_path": annotation_path,
            "coco": coco,
            "ids": selected_ids,
            "repo_paths": [
                image_paths[PurePosixPath(str(coco["images"][image_id]["file_name"])).name]
                for image_id in selected_ids
            ],
        }

    selected_paths = sorted({
        path for split_data in selected.values() for path in split_data["repo_paths"]
    })
    missing_count = sum(
        not (source_root / repository_path).is_file()
        for repository_path in selected_paths
    )
    free_bytes = shutil.disk_usage(source_root).free
    required_gib = missing_count * 5_000_000 / (1024 ** 3) + 2.0
    if free_bytes / (1024 ** 3) < required_gib:
        raise OSError(
            f"Need approximately {required_gib:.1f} GiB free for the uncached selected images and outputs; "
            f"only {free_bytes / (1024 ** 3):.1f} GiB is available. Reduce NEXSAFE_MAX_*."
        )
    hf_workers = int(os.environ.get("NEXSAFE_HF_MAX_WORKERS", "2"))
    if not 1 <= hf_workers <= 8:
        raise ValueError("NEXSAFE_HF_MAX_WORKERS must be between 1 and 8")
    snapshot_download(
        repo_id=UVH_REPO,
        repo_type="dataset",
        revision=UVH_REVISION,
        allow_patterns=selected_paths,
        local_dir=str(source_root),
        max_workers=hf_workers,
    )
    for split, data in selected.items():
        report = _convert_split(
            split,
            data["coco"],
            set(data["ids"]),
            image_paths,
            source_root,
            prepared,
            lambda path: (
                (image.shape[1], image.shape[0])
                if (image := cv2.imread(path, cv2.IMREAD_UNCHANGED)) is not None
                else (None, None)
            ),
        )
        report["annotation_sha256"] = _sha256(data["annotation_path"])
        report["annotation_variant"] = "MV"
        report["publisher_split"] = split
        split_reports[split] = report

    yaml_path = prepared / "data.yaml"
    yaml_path.write_text(
        yaml.safe_dump({
            "path": str(prepared),
            "train": "images/train",
            "val": "images/val",
            "names": {index: name for index, name in enumerate(UVH_CLASSES)},
        }, sort_keys=False),
        encoding="utf-8",
    )
    source_audit = {
        "dataset": "UVH-26",
        "source_url": f"https://huggingface.co/datasets/{UVH_REPO}",
        "revision": UVH_REVISION,
        "license": "CC BY 4.0",
        "image_subset_sampling": "Deterministic per-class image coverage plus seeded random fill; source annotations retained.",
        "selection": {
            "train_images": len(selected["train"]["ids"]),
            "validation_images": len(selected["val"]["ids"]),
            "seed": seed,
            "resumable_cache": str(source_root),
        },
        "publisher_test_split": False,
        "splits": split_reports,
        "base_weights_license_confirmation": "Operator confirmed review via notebook configuration.",
    }
    (prepared / "subset-audit.json").write_text(json.dumps(source_audit, indent=2), encoding="utf-8")

    run_name = f"uvh26-yolo11n-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    model = YOLO("yolo11n.pt")
    base_checkpoint_value = getattr(model, "ckpt_path", "yolo11n.pt")
    if not base_checkpoint_value:
        raise RuntimeError("Ultralytics did not identify the loaded pretrained checkpoint")
    base_checkpoint = Path(base_checkpoint_value).resolve()
    if not base_checkpoint.is_file():
        raise FileNotFoundError(f"Ultralytics pretrained checkpoint is unavailable: {base_checkpoint}")
    base_checkpoint_sha256 = _sha256(base_checkpoint)
    model.train(
        data=str(yaml_path),
        imgsz=image_size,
        epochs=epochs,
        batch=batch,
        device=0,
        seed=seed,
        workers=2,
        patience=max(5, epochs // 4),
        project=str(output_root / "runs"),
        name=run_name,
        exist_ok=False,
        cache=False,
        deterministic=True,
    )
    best = output_root / "runs" / run_name / "weights" / "best.pt"
    if not best.is_file() or best.stat().st_size == 0:
        raise FileNotFoundError(f"YOLO training did not generate a non-empty best checkpoint: {best}")
    training_metrics = _read_training_metrics(best.parent.parent / "results.csv")
    best_model = YOLO(str(best))
    validation = best_model.val(data=str(yaml_path), split="val", device=0, imgsz=image_size)
    metrics = validation.results_dict
    metric_keys = (
        "metrics/precision(B)", "metrics/recall(B)",
        "metrics/mAP50(B)", "metrics/mAP50-95(B)",
    )
    if any(key not in metrics for key in metric_keys):
        raise RuntimeError(f"Validation did not return all required detection metrics: {sorted(metrics)}")
    validation_metrics = {
        key.removeprefix("metrics/").replace("(B)", ""): float(metrics[key])
        for key in metric_keys
    }
    validation_images = sorted((prepared / "images" / "val").glob("*.png"))
    if not validation_images:
        raise FileNotFoundError("No prepared publisher-validation image is available for inference smoke testing")
    inference_image = validation_images[0]
    inference_results = best_model.predict(
        source=str(inference_image),
        device=0,
        imgsz=image_size,
        verbose=False,
    )
    if len(inference_results) != 1 or inference_results[0].orig_shape is None:
        raise RuntimeError("The trained detector did not return a valid result for the validation smoke-test image")
    inference_smoke = {
        "status": "passed",
        "source": "publisher_validation_sample",
        "image": inference_image.name,
        "image_dimensions": {
            "height": int(inference_results[0].orig_shape[0]),
            "width": int(inference_results[0].orig_shape[1]),
        },
        "detections": (
            len(inference_results[0].boxes)
            if inference_results[0].boxes is not None
            else 0
        ),
    }
    export_root = output_root / "nexsafe_export"
    export_root.mkdir(parents=True, exist_ok=False)
    export_checkpoint = export_root / "uvh26-yolo11n.pt"
    shutil.copy2(best, export_checkpoint)
    metadata = {
        "format_version": 1,
        "architecture": "YOLO11",
        "model_version": _sha256(export_checkpoint)[:16],
        "checkpoint_sha256": _sha256(export_checkpoint),
        "classes": {str(index): name for index, name in enumerate(UVH_CLASSES)},
        "dataset": "UVH-26",
        "dataset_revision": UVH_REVISION,
        "license": "CC BY 4.0",
        "annotation_variant": "MV",
        "training_metrics": training_metrics,
        "validation_metrics": validation_metrics,
        "inference_smoke": inference_smoke,
        "test_metrics": None,
        "metrics_note": (
            "Actual validation metrics from the publisher validation split and the selected subset. "
            "UVH-26 contains no held-out test split."
        ),
        "training_info": {
            "base_checkpoint_sha256": base_checkpoint_sha256,
            "base_checkpoint_source": "Ultralytics YOLO11n official asset resolved by pinned Ultralytics package",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_subset_images": split_reports["train"]["images"],
            "validation_subset_images": split_reports["val"]["images"],
            "config": {
                "epochs": epochs, "batch_size": batch, "image_size": image_size,
                "device": torch.cuda.get_device_name(0), "seed": seed,
            },
            "validation_split": "publisher validation subset (seeded sample)",
            "test_split": None,
        },
    }
    sidecar = export_checkpoint.with_suffix(export_checkpoint.suffix + ".nexsafe.json")
    sidecar.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_audit": source_audit,
        "training_status": "completed",
        "checkpoint": str(export_checkpoint),
        "checkpoint_sha256": _sha256(export_checkpoint),
        "metadata": str(sidecar),
        "training_metrics": training_metrics,
        "validation_metrics": validation_metrics,
        "inference_smoke": inference_smoke,
        "test_metrics": None,
    }
    report_path = export_root / "uvh26-training-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            target = (destination / info.filename).resolve()
            if target != base and base not in target.parents:
                raise ValueError(f"Unsafe path in Kaggle archive: {info.filename}")
        source.extractall(destination)


def acquire_accident_dataset(root: Path) -> Path:
    import requests

    if (
        os.environ.get("NEXSAFE_ALLOW_NONCOMMERCIAL_ACCIDENT_USE") != "1"
        and os.environ.get("NEXSAFE_HAVE_SEPARATE_ACCIDENT_LICENSE") != "1"
    ):
        raise PermissionError(
            "ACCIDENT is licensed CC BY-NC-SA 4.0. Confirm strictly non-commercial "
            "use/share-alike obligations or supply separate written permission before use."
        )
    metadata_response = requests.get(
        f"https://www.kaggle.com/api/v1/datasets/view/{ACCIDENT_SLUG}",
        timeout=30,
    )
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    if metadata.get("licenseName") != ACCIDENT_LICENSE:
        raise RuntimeError("Kaggle ACCIDENT license changed; stop and review the current license.")
    if metadata.get("totalBytes") != ACCIDENT_BYTES:
        raise RuntimeError("Kaggle ACCIDENT archive size changed; verify available disk before acquisition.")
    try:
        from kaggle_secrets import UserSecretsClient
    except ImportError as exc:
        raise RuntimeError(
            "Configure Kaggle Secrets named KAGGLE_USERNAME and KAGGLE_KEY, or attach "
            "the authorized dataset as a Kaggle notebook input."
        ) from exc
    secret_client = UserSecretsClient()
    username = secret_client.get_secret("KAGGLE_USERNAME")
    key = secret_client.get_secret("KAGGLE_KEY")
    del secret_client
    if not username or not key:
        raise RuntimeError("Kaggle API secrets are empty; values were not logged.")
    free = shutil.disk_usage(root).free
    if free < 45 * (1024 ** 3):
        raise OSError("Downloading and extracting the 20.16 GB archive requires at least 45 GiB free.")
    download_root = root / "accident_download"
    download_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["KAGGLE_USERNAME"] = username
    environment["KAGGLE_KEY"] = key
    result = subprocess.run(
        ["kaggle", "datasets", "download", "-d", ACCIDENT_SLUG, "-p", str(download_root)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    redacted_stderr = _redact_secrets(result.stderr, username, key)
    del username, key, environment
    if result.returncode:
        raise RuntimeError(
            "Kaggle download failed. Credentials were not printed. "
            f"CLI exit code: {result.returncode}; stderr tail: {redacted_stderr[-1000:]}"
        )
    archives = list(download_root.glob("*.zip"))
    if len(archives) != 1 or archives[0].stat().st_size != ACCIDENT_BYTES:
        raise RuntimeError("Downloaded archive is missing or its byte size differs from Kaggle metadata.")
    extracted = root / "accident_extracted"
    _safe_extract(archives[0], extracted)
    return extracted


def locate_accident_input() -> Path | None:
    input_root = Path("/kaggle/input")
    if not input_root.is_dir():
        return None
    for path in input_root.iterdir():
        if path.is_dir() and (
            any(path.rglob("metadata-real.csv"))
            or any(path.rglob("labels.csv"))
        ):
            return path
    return None


def audit_accident(root: Path) -> dict:
    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))
    from training.audit_datasets import audit_videos

    return audit_videos(root)


def run_temporal_if_prepared(output_root: Path) -> dict:
    backend_root = Path(__file__).resolve().parents[1]
    manifest_root = Path(os.environ.get(
        "NEXSAFE_TEMPORAL_MANIFEST_ROOT",
        "/kaggle/input/nexsafe-temporal-manifests",
    ))
    manifest_paths = {
        split: manifest_root / f"{split}.jsonl"
        for split in ("train", "validation", "test")
    }
    if not all(path.is_file() for path in manifest_paths.values()):
        return {
            "status": "blocked",
            "reason": "No complete, owner-annotated train/validation/test manifests attached.",
        }
    manifests = {}
    for split, path in manifest_paths.items():
        records = []
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                item = json.loads(line)
                required = {
                    "video", "source_video_id", "start_seconds", "end_seconds", "label",
                    "dataset", "license", "data_domain",
                }
                if not isinstance(item, dict) or not required.issubset(item):
                    raise ValueError(f"{path}:{line_number} is missing required provenance/label fields")
                if item["data_domain"] != "real":
                    raise ValueError("Real accident detection must not mix in synthetic segments.")
                if not isinstance(item["license"], str) or item["license"].strip().casefold() in {
                    "unknown", "unverified", "none", "n/a", "na",
                }:
                    raise ValueError("Temporal training manifest includes unverified license terms.")
                video = Path(item["video"])
                if not video.is_absolute():
                    video = path.parent / video
                if not video.is_file():
                    raise FileNotFoundError(f"Manifest video not found: {video}")
                item["video"] = str(video.resolve())
                records.append(item)
        manifests[split] = records
    class_sets = [{item["label"] for item in records} for records in manifests.values()]
    if not class_sets[0] or class_sets[0] != class_sets[1] or class_sets[0] != class_sets[2]:
        raise ValueError("Every temporal split must contain the same actual ground-truth labels.")
    normalized_classes = {label.strip().casefold() for label in class_sets[0]}
    negative_labels = {
        label.strip().casefold()
        for label in os.environ.get(
            "NEXSAFE_NEGATIVE_LABELS",
            "no_accident,non_accident,safe,normal,negative",
        ).split(",")
        if label.strip()
    }
    positive_labels = {
        label.strip().casefold()
        for label in os.environ.get("NEXSAFE_POSITIVE_LABELS", "accident,near_miss").split(",")
        if label.strip()
    }
    if not normalized_classes & negative_labels:
        return {
            "status": "blocked",
            "reason": (
                "No explicitly annotated no-accident/safe videos are present. ACCIDENT's real "
                "subset contains accident clips; it cannot alone train accident-vs-safe detection."
            ),
        }
    if not normalized_classes & positive_labels:
        return {
            "status": "blocked",
            "reason": (
                "The manifests have no explicitly configured accident/near-miss label. "
                "Set NEXSAFE_POSITIVE_LABELS to exact ground-truth labels after reviewing the source."
            ),
        }
    sources = [{item["source_video_id"] for item in items} for items in manifests.values()]
    if sources[0] & sources[1] or sources[0] & sources[2] or sources[1] & sources[2]:
        raise ValueError("Source videos must be disjoint across all temporal splits.")
    output = output_root / "nexsafe_export" / "accident-real-cnnlstm.pt"
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend_root) + os.pathsep + environment.get("PYTHONPATH", "")
    dataset_names = {item["dataset"] for records in manifests.values() for item in records}
    if len(dataset_names) != 1:
        raise ValueError("Use one dataset per temporal model run and report each data source separately.")
    command = [
        sys.executable, "-m", "training.train_temporal",
        "--train-manifest", str(manifest_paths["train"]),
        "--validation-manifest", str(manifest_paths["validation"]),
        "--test-manifest", str(manifest_paths["test"]),
        "--dataset-name", next(iter(dataset_names)),
        "--output", str(output),
        "--device", "cuda",
    ]
    result = subprocess.run(
        command, cwd=backend_root, env=environment, check=False,
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"Temporal training failed; stderr tail: {result.stderr[-3000:]}")
    return {"status": "completed", "checkpoint": str(output), "trainer_output": result.stdout[-3000:]}


def run_structured_if_prepared(output_root: Path) -> dict:
    backend_root = Path(__file__).resolve().parents[1]
    csv_root = Path(os.environ.get(
        "NEXSAFE_ROAD_RISK_CSV_ROOT",
        "/kaggle/input/nexsafe-road-risk",
    ))
    split_paths = {
        split: csv_root / f"{split}.csv"
        for split in ("train", "validation", "test")
    }
    if not all(path.is_file() for path in split_paths.values()):
        return {"status": "blocked", "reason": "No owner-provided, labeled train/validation/test road-risk CSVs attached."}
    required_settings = {
        "NEXSAFE_RISK_TARGET": "observed target column",
        "NEXSAFE_RISK_GROUP_COLUMN": "leakage group column",
        "NEXSAFE_RISK_FEATURES": "pre-outcome numeric feature columns",
        "NEXSAFE_RISK_DATASET": "dataset name",
        "NEXSAFE_RISK_LABEL_DEFINITION": "observed target definition",
        "NEXSAFE_RISK_LICENSE": "source license",
    }
    missing = [description for key, description in required_settings.items() if not os.environ.get(key, "").strip()]
    if missing:
        return {"status": "blocked", "reason": "Set explicit model provenance/semantics: " + ", ".join(missing)}
    output = output_root / "nexsafe_export" / "road-risk.pt"
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend_root) + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        sys.executable, "-m", "training.train_structured_risk",
        "--train-csv", str(split_paths["train"]),
        "--validation-csv", str(split_paths["validation"]),
        "--test-csv", str(split_paths["test"]),
        "--target", environment["NEXSAFE_RISK_TARGET"],
        "--group-column", environment["NEXSAFE_RISK_GROUP_COLUMN"],
        "--features", environment["NEXSAFE_RISK_FEATURES"],
        "--dataset-name", environment["NEXSAFE_RISK_DATASET"],
        "--label-definition", environment["NEXSAFE_RISK_LABEL_DEFINITION"],
        "--license", environment["NEXSAFE_RISK_LICENSE"],
        "--output", str(output),
        "--device", "cuda",
    ]
    result = subprocess.run(
        command, cwd=backend_root, env=environment, check=False,
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"Structured risk training failed; stderr tail: {result.stderr[-3000:]}")
    return {"status": "completed", "checkpoint": str(output), "trainer_output": result.stdout[-3000:]}


def main() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path("/kaggle/working/nexsafe_training") / run_id
    output_root.mkdir(parents=True, exist_ok=False)
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("GPU unavailable: set a Kaggle GPU accelerator, then restart and rerun.")
    print("GPU:", torch.cuda.get_device_name(0))
    print("Working free GiB:", round(shutil.disk_usage("/kaggle/working").free / (1024 ** 3), 2))
    detector_report = train_detector(output_root)
    print("UVH-26 detector training completed:", json.dumps(detector_report, indent=2))

    accident_root = locate_accident_input()
    if os.environ.get("NEXSAFE_DOWNLOAD_ACCIDENT") == "1":
        accident_root = acquire_accident_dataset(output_root)
    if accident_root:
        if (
            os.environ.get("NEXSAFE_ALLOW_NONCOMMERCIAL_ACCIDENT_USE") != "1"
            and os.environ.get("NEXSAFE_HAVE_SEPARATE_ACCIDENT_LICENSE") != "1"
        ):
            raise PermissionError(
                "ACCIDENT input is present but its CC BY-NC-SA terms have not been accepted/cleared."
            )
        accident_report = audit_accident(accident_root)
        (output_root / "accident-dataset-audit.json").write_text(
            json.dumps(accident_report, indent=2), encoding="utf-8"
        )
        print("ACCIDENT dataset audit status:", accident_report["audit_status"])
        print("ACCIDENT metadata fields/labels are reported only; no collision labels are inferred.")
    else:
        print("ACCIDENT dataset status: not attached/downloaded; no accident training attempted.")

    temporal_report = run_temporal_if_prepared(output_root)
    print("Temporal model status:", json.dumps(temporal_report, indent=2))
    risk_report = run_structured_if_prepared(output_root)
    print("Structured road-risk model status:", json.dumps(risk_report, indent=2))
    print("Training run artifacts are under:", output_root)


if __name__ == "__main__":
    main()
