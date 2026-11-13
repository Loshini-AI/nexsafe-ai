import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("nexsafe.dataset")


def load_dataset_status() -> dict[str, Any]:
    try:
        audit = json.loads(Path(settings.dataset_audit_path).read_text(encoding="utf-8"))
        catalog = json.loads(Path(settings.dataset_catalog_path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.warning("Dataset status file is unavailable: %s", exc.filename)
        return {
            "status": "unavailable",
            "message": "A local dataset audit or source catalog is missing.",
            "last_audited": None,
            "dataset": None,
            "splits": [],
        }
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Dataset status could not be loaded")
        return {
            "status": "error",
            "message": f"Dataset status could not be loaded: {type(exc).__name__}.",
            "last_audited": None,
            "dataset": None,
            "splits": [],
        }

    if not isinstance(audit, dict) or not isinstance(catalog, dict):
        logger.error("Dataset audit or catalog root is not a JSON object")
        return {
            "status": "error",
            "message": "The dataset audit or source catalog has an invalid format.",
            "last_audited": None,
            "dataset": None,
            "splits": [],
        }

    audit_datasets = audit.get("datasets")
    uvh26 = audit_datasets.get("uvh26") if isinstance(audit_datasets, dict) else None
    sources = catalog.get("sources")
    source = next(
        (item for item in sources if isinstance(item, dict) and item.get("id") == "uvh-26"),
        None,
    ) if isinstance(sources, list) else None
    if not isinstance(uvh26, dict) or not isinstance(source, dict):
        logger.error("Dataset audit or catalog is missing the UVH-26 record")
        return {
            "status": "error",
            "message": "The dataset audit or source catalog has no UVH-26 record.",
            "last_audited": audit.get("generated_at"),
            "dataset": None,
            "splits": [],
        }

    split_records = uvh26.get("splits")
    if (
        not isinstance(split_records, list)
        or not split_records
        or not all(isinstance(item, dict) for item in split_records)
    ):
        logger.error("UVH-26 dataset audit has no split records")
        return {
            "status": "error",
            "message": "The UVH-26 audit report does not contain split details.",
            "last_audited": audit.get("generated_at"),
            "dataset": None,
            "splits": [],
        }

    split_statuses = [item.get("audit_status") for item in split_records]
    audit_status = uvh26.get("audit_status")
    if (
        audit_status not in {"complete", "incomplete"}
        or any(item not in {"complete", "incomplete"} for item in split_statuses)
    ):
        logger.error("UVH-26 audit has an unrecognized status: %r", audit_status)
        return {
            "status": "error",
            "message": "The UVH-26 audit report has an unrecognized status.",
            "last_audited": audit.get("generated_at"),
            "dataset": None,
            "splits": [],
        }

    status = (
        "complete"
        if audit_status == "complete" and all(item == "complete" for item in split_statuses)
        else "incomplete"
    )
    logger.info(
        "Loaded %s dataset audit: status=%s split_count=%d",
        source.get("name"),
        status,
        len(split_records),
    )

    def dimension_mismatch_count(item: dict[str, Any]) -> int | None:
        mismatches = item.get("image_dimension_mismatches")
        return len(mismatches) if isinstance(mismatches, list) else None

    return {
        "status": status,
        "message": (
            "The local audit is incomplete. UVH-26 has vehicle-detection labels, "
            "not accident-risk labels; it cannot substantiate accident-risk training."
            if status == "incomplete"
            else "Audit complete. UVH-26 supports vehicle detection only, not accident-risk training."
        ),
        "last_audited": audit.get("generated_at"),
        "dataset": {
            "name": source.get("name"),
            "source": source.get("url"),
            "license": uvh26.get("license", source.get("license")),
            "revision": uvh26.get("revision"),
            "supported_tasks": source.get("supported_tasks", []),
            "not_supported": source.get("not_supported", []),
        },
        "splits": [
            {
                "name": item.get("split"),
                "status": item.get("audit_status"),
                "available_images": item.get("png_files"),
                "annotated_images": item.get("images"),
                "missing_images": item.get("missing_images"),
                "annotations": item.get("annotation_count"),
                "image_bytes": item.get("image_bytes"),
                "dimension_mismatches": dimension_mismatch_count(item),
            }
            for item in split_records
            if isinstance(item, dict)
        ],
    }
