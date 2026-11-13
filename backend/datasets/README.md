# Dataset intake

The source ledger is [`catalog.json`](./catalog.json). It records reported
source access, licensing, labels, and limitations; it does not track the
machine-local acquisition state. Source media is not bundled with the
application. The current local UVH-26 acquisition and audit status is recorded
in the root [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md).

## UVH-26

The public Hugging Face repository reports 26,646 still images with COCO
annotations, a publisher train/validation split, 14 vehicle classes, and CC BY
4.0 terms. The pinned image payload is about 89.84 GB. The downloader is
explicit, pins the source revision, requires license acknowledgement, and
does not run during app startup. Hugging Face may rate-limit anonymous
downloads; authenticate using `hf auth login` in the same Python environment.

```powershell
cd backend
python -m training.download_uvh26 --split train --max-workers 1 --acknowledge-license
python -m training.prepare_uvh26 --root ..\data\datasets\uvh26 --output ..\data\prepared\uvh26
```

Train / validation conversion uses the publisher's existing split. The source
has no held-out test split. It also labels `Two-wheeler` rather than separate
motorcycle and scooter classes and has no pedestrian class; those labels are
never invented during conversion.

## Accident video and IDD sources

ACCIDENT's current Kaggle metadata lists CC BY-NC-SA 4.0. Use only after
reviewing/accepting those non-commercial, attribution, and share-alike terms;
commercial use requires separate written permission. Kaggle authentication is
required for API acquisition. IDD requires registration and displays its
license before download; its image segmentation
labels are not accident labels. The IITH URL provided in the request returned
404. TU-DAT's article describes about 280 mixed real/simulated videos and is
published under CC BY 4.0, but that does not establish the license of every
underlying media item; obtain and verify dataset-specific terms and labels.
None of these sources are automatically fetched or mapped into crash labels.

## Train only on traceable labels

For temporal accident classification and structured risk experiments, prepare
JSONL manifests/CSV from the dataset owners' actual annotations. Each temporal
record must include `video`, `source_video_id`, `start_seconds`,
`end_seconds`, `label`, `dataset`, and `license`. Partition by
`source_video_id` into separate train, validation, and test files. The trainer
rejects overlapping source videos and incomplete provenance. Keep synthetic
and real domains distinguishable; report separate evaluation where both are
used. Collision-type classes are valid only when explicitly annotated.

For structured risk, supply a CSV whose target is an observed, well-defined
outcome from a lawful source. Predictions, arbitrary thresholds, and
weather-only heuristics are not acceptable ground-truth labels.
