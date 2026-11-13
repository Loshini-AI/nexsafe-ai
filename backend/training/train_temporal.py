import argparse
import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from app.training_model import CNNLSTM


def read_manifest(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as manifest:
        for line_number, line in enumerate(manifest, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            required = {
                "video", "start_seconds", "end_seconds", "label", "source_video_id",
                "dataset", "license", "data_domain",
            }
            if not isinstance(item, dict) or not required.issubset(item):
                raise ValueError(
                    f"{path}:{line_number} requires video, source_video_id, start_seconds, "
                    "end_seconds, label, dataset, license, and data_domain"
                )
            video = Path(item["video"])
            if not video.is_absolute():
                video = path.parent / video
            if not video.is_file():
                raise FileNotFoundError(f"{path}:{line_number} video not found: {video}")
            start = float(item["start_seconds"])
            end = float(item["end_seconds"])
            label = str(item["label"]).strip()
            source_video_id = str(item["source_video_id"]).strip()
            dataset = str(item["dataset"]).strip()
            license_name = str(item["license"]).strip()
            data_domain = str(item["data_domain"]).strip().casefold()
            if (
                not label or not source_video_id or not dataset or not license_name
                or license_name.casefold() in {"unknown", "unverified", "none", "n/a", "na"}
                or data_domain not in {"real", "synthetic"}
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start
            ):
                raise ValueError(f"{path}:{line_number} has invalid time interval or label")
            records.append({"video": str(video.resolve()), "start_seconds": start,
                            "end_seconds": end, "label": label,
                            "source_video_id": source_video_id, "dataset": dataset,
                            "license": license_name, "data_domain": data_domain})
    if not records:
        raise ValueError(f"Dataset manifest has no labeled video segments: {path}")
    return records


class VideoSequenceDataset(Dataset):
    def __init__(
        self,
        records: list[dict],
        classes: list[str],
        sequence_length: int,
        image_size: int,
        window_seconds: float,
    ):
        self.records = records
        self.class_ids = {name: index for index, name in enumerate(classes)}
        self.sequence_length = sequence_length
        self.image_size = image_size
        self.window_seconds = window_seconds

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        item = self.records[index]
        capture = cv2.VideoCapture(item["video"])
        if not capture.isOpened():
            raise RuntimeError(f"Could not open labeled video: {item['video']}")
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not np.isfinite(fps) or fps <= 0:
                raise ValueError(f"Video has no valid recorded frame rate; refusing assumed timing: {item['video']}")
            if item["end_seconds"] - item["start_seconds"] < self.window_seconds:
                raise ValueError(f"Labeled segment must be at least {self.window_seconds}s: {item['video']}")
            frame_indices = np.linspace(
                item["start_seconds"] * fps,
                (item["start_seconds"] + self.window_seconds) * fps,
                num=self.sequence_length,
                endpoint=False,
            ).astype(np.int64)
            frames = []
            for frame_index in frame_indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(
                        f"Could not read frame {frame_index} from labeled video {item['video']}"
                    )
                frame = cv2.resize(frame, (self.image_size, self.image_size), interpolation=cv2.INTER_AREA)
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        finally:
            capture.release()
        array = np.stack(frames).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(0, 3, 1, 2)
        return tensor, self.class_ids[item["label"]]


def calculate_metrics(expected: list[int], predicted: list[int], classes: list[str], split: str) -> dict:
    per_class = {}
    f1_values = []
    precision_values = []
    recall_values = []
    for class_id, label in enumerate(classes):
        true_positive = sum(actual == class_id and guess == class_id for actual, guess in zip(expected, predicted))
        false_positive = sum(actual != class_id and guess == class_id for actual, guess in zip(expected, predicted))
        false_negative = sum(actual == class_id and guess != class_id for actual, guess in zip(expected, predicted))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1,
                            "support": sum(actual == class_id for actual in expected)}
        precision_values.append(precision)
        recall_values.append(recall)
        f1_values.append(f1)
    accuracy = sum(actual == guess for actual, guess in zip(expected, predicted)) / len(expected)
    return {
        "accuracy": accuracy,
        "macro_precision": sum(precision_values) / len(classes),
        "macro_recall": sum(recall_values) / len(classes),
        "macro_f1": sum(f1_values) / len(classes),
        "per_class": per_class,
        f"{split}_segments": len(expected),
    }


def evaluate(model, loader, device) -> tuple[list[int], list[int]]:
    expected = []
    predicted = []
    model.eval()
    with torch.inference_mode():
        for sequences, labels in loader:
            logits = model(sequences.to(device))
            expected.extend(labels.tolist())
            predicted.extend(logits.argmax(dim=1).cpu().tolist())
    return expected, predicted


def train(args) -> None:
    if not args.dataset_name.strip():
        raise ValueError("--dataset-name must identify the real training dataset")
    train_manifest = Path(args.train_manifest).resolve()
    validation_manifest = Path(args.validation_manifest).resolve()
    test_manifest = Path(args.test_manifest).resolve()
    training = read_manifest(train_manifest)
    validation = read_manifest(validation_manifest)
    test = read_manifest(test_manifest)
    classes = sorted({item["label"] for item in training})
    if len(classes) < 2:
        raise ValueError("Training manifest must contain at least two distinct labeled classes")
    if {item["label"] for item in validation} != set(classes):
        raise ValueError("Validation manifest must contain every training class and no other classes")
    if {item["label"] for item in test} != set(classes):
        raise ValueError("Test manifest must contain every training class and no other classes")
    split_sources = [
        {item["source_video_id"] for item in split}
        for split in (training, validation, test)
    ]
    split_paths = [
        {item["video"] for item in split}
        for split in (training, validation, test)
    ]
    if (
        split_sources[0] & split_sources[1]
        or split_sources[0] & split_sources[2]
        or split_sources[1] & split_sources[2]
        or split_paths[0] & split_paths[1]
        or split_paths[0] & split_paths[2]
        or split_paths[1] & split_paths[2]
    ):
        raise ValueError("A source video cannot occur in more than one train/validation/test manifest")
    provenance = {
        (item["dataset"], item["license"])
        for split in (training, validation, test)
        for item in split
    }
    if len({item["dataset"] for item in provenance}) != 1:
        raise ValueError("A training run must use one explicitly named dataset; report mixed sources separately")
    data_domains = {
        item["data_domain"]
        for split in (training, validation, test)
        for item in split
    }
    if len(data_domains) != 1:
        raise ValueError("Real and synthetic videos must be trained/evaluated as separate model runs")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    train_data = VideoSequenceDataset(
        training, classes, args.sequence_length, args.image_size, args.window_seconds
    )
    validation_data = VideoSequenceDataset(
        validation, classes, args.sequence_length, args.image_size, args.window_seconds
    )
    test_data = VideoSequenceDataset(
        test, classes, args.sequence_length, args.image_size, args.window_seconds
    )
    train_loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True, num_workers=0)
    validation_loader = DataLoader(validation_data, batch_size=args.batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_data, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = CNNLSTM(len(classes)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    criterion = torch.nn.CrossEntropyLoss()
    best_validation_f1 = -1.0
    best_validation_metrics = None
    best_epoch = 0
    best_state_dict = None
    history_path = Path(args.history).resolve() if args.history else Path(args.output).resolve().with_suffix(".history.jsonl")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        for sequences, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(sequences.to(device)), labels.to(device))
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
        expected, predicted = evaluate(model, validation_loader, device)
        metrics = calculate_metrics(expected, predicted, classes, "validation")
        epoch_result = {"epoch": epoch + 1, "training_loss": running_loss / len(train_loader),
                        "validation": metrics}
        print(json.dumps(epoch_result, sort_keys=True))
        with history_path.open("a", encoding="utf-8") as history:
            history.write(json.dumps(epoch_result, sort_keys=True) + "\n")
        if metrics["macro_f1"] > best_validation_f1:
            best_validation_f1 = metrics["macro_f1"]
            best_validation_metrics = metrics
            best_epoch = epoch + 1
            best_state_dict = {
                name: tensor.detach().cpu().clone()
                for name, tensor in model.state_dict().items()
            }
    if best_state_dict is None or best_validation_metrics is None:
        raise RuntimeError("Training completed without a best validation checkpoint")
    model.load_state_dict(best_state_dict)
    test_expected, test_predicted = evaluate(model, test_loader, device)
    test_metrics = calculate_metrics(test_expected, test_predicted, classes, "test")

    def file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    information = {
        "dataset_name": args.dataset_name,
        "train_manifest_sha256": file_digest(train_manifest),
        "validation_manifest_sha256": file_digest(validation_manifest),
        "test_manifest_sha256": file_digest(test_manifest),
        "train_segments": len(training),
        "validation_segments": len(validation),
        "test_segments": len(test),
        "train_label_counts": dict(Counter(item["label"] for item in training)),
        "validation_label_counts": dict(Counter(item["label"] for item in validation)),
        "test_label_counts": dict(Counter(item["label"] for item in test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "epochs": args.epochs,
        "best_epoch": best_epoch,
        "seed": args.seed,
        "window_seconds": args.window_seconds,
        "provenance": sorted(
            [{"dataset": dataset, "license": license_name} for dataset, license_name in provenance],
            key=lambda item: (item["dataset"], item["license"]),
        ),
        "data_domain": next(iter(data_domains)),
    }
    state_dict = model.cpu().state_dict()
    model_digest = hashlib.sha256()
    for name, tensor in sorted(state_dict.items()):
        model_digest.update(name.encode("utf-8"))
        model_digest.update(tensor.contiguous().numpy().tobytes())
    model_version = model_digest.hexdigest()[:16]
    checkpoint = {
        "format_version": 1,
        "architecture": "CNNLSTM",
        "state_dict": state_dict,
        "classes": classes,
        "sequence_length": args.sequence_length,
        "image_size": args.image_size,
        "window_seconds": args.window_seconds,
        "model_version": model_version,
        "validation_metrics": best_validation_metrics,
        "test_metrics": test_metrics,
        "training_info": information,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            torch.save(checkpoint, file)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({"checkpoint": str(output), "sha256": digest, "model_version": model_version, "classes": classes,
                      "validation_metrics": best_validation_metrics, "test_metrics": test_metrics,
                      "training_info": information}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and validate NexSafe's CNN-LSTM using real labeled video segments.")
    parser.add_argument("--train-manifest", required=True)
    parser.add_argument("--validation-manifest", required=True)
    parser.add_argument("--test-manifest", required=True, help="Independent held-out videos; never tune on this split")
    parser.add_argument("--dataset-name", required=True, help="Name and provenance of the lawfully obtained source dataset")
    parser.add_argument("--output", required=True)
    parser.add_argument("--history", help="Append per-epoch validation results as JSONL")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--sequence-length", type=int, default=16)
    parser.add_argument("--image-size", type=int, default=112)
    parser.add_argument("--window-seconds", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if (
        args.epochs < 1 or args.batch_size < 1 or args.sequence_length < 2
        or args.image_size < 32 or args.window_seconds <= 0
    ):
        parser.error("epochs/batch size must be positive, sequence length >= 2, and image size >= 32")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA was requested but is unavailable")
    train(args)


if __name__ == "__main__":
    main()
