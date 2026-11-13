import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ultralytics import YOLO


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fine-tune a locally supplied Ultralytics YOLO11 checkpoint on prepared UVH-26 data."
    )
    parser.add_argument("--data", type=Path, required=True, help="Prepared dataset data.yaml")
    parser.add_argument("--base-weights", type=Path, required=True, help="Local, licensed YOLO checkpoint")
    parser.add_argument("--config", type=Path, default=Path("configs/detector_uvh26.json"))
    parser.add_argument("--output", type=Path, required=True, help="Destination for best.pt and its metadata")
    args = parser.parse_args()
    data_file = args.data.resolve()
    base_weights = args.base_weights.resolve()
    config_file = args.config.resolve()
    output = args.output.resolve()
    if not data_file.is_file() or not base_weights.is_file() or not config_file.is_file():
        parser.error("--data, --base-weights, and --config must all exist as local files")
    if output.exists():
        parser.error(f"Refusing to overwrite an existing checkpoint: {output}")

    config = json.loads(config_file.read_text(encoding="utf-8"))
    required = {"architecture", "image_size", "epochs", "batch_size", "device", "seed", "workers", "patience", "project", "name"}
    if not required.issubset(config) or config["architecture"] != "YOLO11":
        parser.error(f"Training config must include {sorted(required)} and architecture YOLO11")
    dataset_root = data_file.parent
    prep_report_path = dataset_root / "preparation-report.json"
    if not prep_report_path.is_file():
        parser.error("Prepared data is missing preparation-report.json; use training.prepare_uvh26 first")
    prep_report = json.loads(prep_report_path.read_text(encoding="utf-8"))
    if prep_report.get("dataset") != "UVH-26" or prep_report.get("license") != "CC BY 4.0":
        parser.error("Dataset preparation report is not verified UVH-26 metadata")
    if not isinstance(prep_report.get("results"), list) or {
        item.get("split") for item in prep_report["results"]
    } != {"train", "val"}:
        parser.error("UVH-26 training requires the publisher's train and validation splits")

    model = YOLO(str(base_weights))
    result = model.train(
        data=str(data_file),
        imgsz=int(config["image_size"]),
        epochs=int(config["epochs"]),
        batch=int(config["batch_size"]),
        device=config["device"],
        seed=int(config["seed"]),
        workers=int(config["workers"]),
        patience=int(config["patience"]),
        project=str(config["project"]),
        name=str(config["name"]),
        exist_ok=False,
        deterministic=True,
    )
    best_checkpoint = Path(result.save_dir) / "weights" / "best.pt"
    if not best_checkpoint.is_file():
        raise FileNotFoundError(f"Ultralytics training did not produce best.pt: {best_checkpoint}")
    metrics = getattr(result, "results_dict", None)
    if not isinstance(metrics, dict):
        raise RuntimeError("Training completed without validation metrics")
    required_metric_names = (
        "metrics/precision(B)",
        "metrics/recall(B)",
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
    )
    if any(name not in metrics for name in required_metric_names):
        raise RuntimeError(f"Training returned incomplete validation metrics: {sorted(metrics)}")
    validation_metrics = {
        key.removeprefix("metrics/").replace("(B)", ""): float(metrics[key])
        for key in required_metric_names
    }
    trained_model = YOLO(str(best_checkpoint))

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_checkpoint, output)
    checkpoint_hash = sha256_file(output)
    metadata = {
        "format_version": 1,
        "architecture": "YOLO11",
        "model_version": checkpoint_hash[:16],
        "checkpoint_sha256": checkpoint_hash,
        "classes": {str(key): value for key, value in trained_model.names.items()},
        "dataset": "UVH-26",
        "dataset_revision": prep_report["revision"],
        "license": prep_report["license"],
        "annotation_variant": prep_report["annotation_variant"],
        "training_metrics": None,
        "validation_metrics": validation_metrics,
        "test_metrics": None,
        "metrics_note": "UVH-26 supplies train/validation only; no held-out test metrics are available.",
        "training_info": {
            "base_checkpoint_sha256": sha256_file(base_weights),
            "prepared_data_yaml_sha256": sha256_file(data_file),
            "preparation_report_sha256": sha256_file(prep_report_path),
            "config": config,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "validation_split": "publisher-provided UVH-26 validation",
            "test_split": None,
        },
    }
    metadata_path = output.with_suffix(output.suffix + ".nexsafe.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"checkpoint": str(output), "metadata": str(metadata_path), **metadata}, indent=2))


if __name__ == "__main__":
    main()
