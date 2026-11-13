import argparse
import csv
import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from app.structured_risk_model import RoadRiskMLP


def read_csv(path: Path, label_column: str, group_column: str, feature_columns: list[str]):
    records = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {label_column, group_column, *feature_columns}.issubset(reader.fieldnames):
            raise ValueError(f"{path} must contain label, source group, and all selected feature columns")
        for line_number, row in enumerate(reader, 2):
            label = (row.get(label_column) or "").strip()
            group = (row.get(group_column) or "").strip()
            if not label or not group:
                raise ValueError(f"{path}:{line_number} has empty label or source group")
            try:
                values = [float(row[column]) for column in feature_columns]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number} has a missing/non-numeric feature") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"{path}:{line_number} has a non-finite feature")
            records.append({"features": values, "label": label, "group": group})
    if not records:
        raise ValueError(f"No records in {path}")
    return records


def metrics(expected: list[int], predicted: list[int], classes: list[str], split_name: str):
    per_class = {}
    f1_scores = []
    precision_scores = []
    recall_scores = []
    for index, name in enumerate(classes):
        tp = sum(actual == index and guess == index for actual, guess in zip(expected, predicted))
        fp = sum(actual != index and guess == index for actual, guess in zip(expected, predicted))
        fn = sum(actual == index and guess != index for actual, guess in zip(expected, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_scores.append(f1)
        precision_scores.append(precision)
        recall_scores.append(recall)
        per_class[name] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(v == index for v in expected)}
    return {
        "accuracy": sum(actual == guess for actual, guess in zip(expected, predicted)) / len(expected),
        "macro_f1": sum(f1_scores) / len(f1_scores),
        "macro_precision": sum(precision_scores) / len(precision_scores),
        "macro_recall": sum(recall_scores) / len(recall_scores),
        "per_class": per_class,
        f"{split_name}_records": len(expected),
    }


def evaluate(model, loader, device):
    expected, predicted = [], []
    model.eval()
    with torch.inference_mode():
        for features, labels in loader:
            logits = model(features.to(device))
            expected.extend(labels.tolist())
            predicted.extend(logits.argmax(dim=1).cpu().tolist())
    return expected, predicted


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def train(args):
    train_path, validation_path, test_path = (
        Path(args.train_csv).resolve(),
        Path(args.validation_csv).resolve(),
        Path(args.test_csv).resolve(),
    )
    feature_columns = [column.strip() for column in args.features.split(",") if column.strip()]
    if not feature_columns or len(set(feature_columns)) != len(feature_columns):
        raise ValueError("--features must name distinct numeric CSV columns")
    if args.target in feature_columns or args.group_column in feature_columns:
        raise ValueError("Label and group columns cannot also be model features")
    splits = [
        read_csv(path, args.target, args.group_column, feature_columns)
        for path in (train_path, validation_path, test_path)
    ]
    source_groups = [{item["group"] for item in split} for split in splits]
    if source_groups[0] & source_groups[1] or source_groups[0] & source_groups[2] or source_groups[1] & source_groups[2]:
        raise ValueError("Source groups must be disjoint across train, validation, and test")
    classes = sorted({item["label"] for item in splits[0]})
    if len(classes) < 2 or any({item["label"] for item in split} != set(classes) for split in splits[1:]):
        raise ValueError("All three splits must contain the same two-or-more observed target classes")
    if not args.dataset_name.strip() or not args.label_definition.strip() or not args.license.strip():
        raise ValueError("Dataset name, observed target definition, and license/provenance are required")

    train_values = np.asarray([item["features"] for item in splits[0]], dtype=np.float32)
    mean = train_values.mean(axis=0)
    scale = train_values.std(axis=0)
    scale[scale == 0] = 1.0
    class_ids = {name: index for index, name in enumerate(classes)}

    def loader(records, shuffle):
        values = (np.asarray([item["features"] for item in records], dtype=np.float32) - mean) / scale
        labels = np.asarray([class_ids[item["label"]] for item in records], dtype=np.int64)
        return DataLoader(TensorDataset(torch.from_numpy(values), torch.from_numpy(labels)),
                          batch_size=args.batch_size, shuffle=shuffle)

    train_loader, validation_loader, test_loader = (
        loader(splits[0], True), loader(splits[1], False), loader(splits[2], False)
    )
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device(args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu"))
    model = RoadRiskMLP(len(feature_columns), len(classes)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_function = torch.nn.CrossEntropyLoss()
    best_f1 = -1.0
    best_validation_metrics = None
    best_state = None
    best_epoch = 0
    history_path = Path(args.history).resolve() if args.history else Path(args.output).resolve().with_suffix(".history.jsonl")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        model.train()
        for values, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(values.to(device)), labels.to(device))
            loss.backward()
            optimizer.step()
        expected, predicted = evaluate(model, validation_loader, device)
        current_metrics = metrics(expected, predicted, classes, "validation")
        epoch_result = {"epoch": epoch + 1, **current_metrics}
        print(json.dumps(epoch_result, sort_keys=True))
        with history_path.open("a", encoding="utf-8") as history:
            history.write(json.dumps(epoch_result, sort_keys=True) + "\n")
        if current_metrics["macro_f1"] > best_f1:
            best_f1 = current_metrics["macro_f1"]
            best_validation_metrics = current_metrics
            best_epoch = epoch + 1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    if best_state is None or best_validation_metrics is None:
        raise RuntimeError("No best validation checkpoint was produced")
    model.load_state_dict(best_state)
    expected, predicted = evaluate(model, test_loader, device)
    test_metrics = metrics(expected, predicted, classes, "test")
    state_dict = model.cpu().state_dict()
    digest = hashlib.sha256()
    for key, value in sorted(state_dict.items()):
        digest.update(key.encode())
        digest.update(value.contiguous().numpy().tobytes())
    model_version = digest.hexdigest()[:16]
    checkpoint = {
        "format_version": 1,
        "architecture": "RoadRiskMLP",
        "state_dict": state_dict,
        "feature_names": feature_columns,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "classes": classes,
        "model_version": model_version,
        "validation_metrics": best_validation_metrics,
        "test_metrics": test_metrics,
        "training_info": {
            "dataset_name": args.dataset_name,
            "label_definition": args.label_definition,
            "license": args.license,
            "group_column": args.group_column,
            "train_records": len(splits[0]),
            "validation_records": len(splits[1]),
            "test_records": len(splits[2]),
            "train_label_counts": dict(Counter(item["label"] for item in splits[0])),
            "validation_label_counts": dict(Counter(item["label"] for item in splits[1])),
            "test_label_counts": dict(Counter(item["label"] for item in splits[2])),
            "train_csv_sha256": sha256(train_path),
            "validation_csv_sha256": sha256(validation_path),
            "test_csv_sha256": sha256(test_path),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "best_epoch": best_epoch,
            "device": str(device),
            "seed": args.seed,
        },
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            torch.save(checkpoint, target)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    print(json.dumps({
        "checkpoint": str(output),
        "checkpoint_sha256": sha256(output),
        "model_version": model_version,
        "validation_metrics": best_validation_metrics,
        "test_metrics": test_metrics,
        "training_info": checkpoint["training_info"],
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description="Train a road-risk MLP on observed, provenance-backed structured records.")
    parser.add_argument("--train-csv", required=True)
    parser.add_argument("--validation-csv", required=True)
    parser.add_argument("--test-csv", required=True)
    parser.add_argument("--target", required=True, help="Observed outcome column; never a model-generated score")
    parser.add_argument("--group-column", required=True, help="Leakage-safe geographic/time/source group identifier")
    parser.add_argument("--features", required=True, help="Comma-separated numeric, pre-outcome feature columns")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--label-definition", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--history", help="Append per-epoch validation metrics as JSONL")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or args.learning_rate <= 0:
        parser.error("epochs, batch size, and learning rate must be positive")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA was requested but is unavailable")
    train(args)


if __name__ == "__main__":
    main()
