# NexSafe model training

The application ships with training code, not trained weights or source media.
`backend/datasets/catalog.json` records actual source accessibility, licensing,
size, labels, and limitations. The IITH URL was unavailable when checked.
Kaggle's current public metadata lists ACCIDENT under **CC BY-NC-SA 4.0**
(non-commercial, share-alike) with a 20,158,641,093-byte archive. Local Kaggle
credentials are absent. Do not use that data for commercial NexSafe deployments
without separate written rights-holder permission. Non-commercial research
still requires attribution and compliance with share-alike terms. IDD requires
registration and license review; TU-DAT media terms/download have not been
verified. No source media is bundled.

Install the base API and test dependencies on Windows (Python 3.11) with
`.\setup-windows.ps1`. This creates `.venv-backend311` without installing
PyTorch or CUDA. The API safely leaves model inference unavailable until its
optional vision dependencies and actual weights are configured.

Install the full vision/training requirements only where model execution is
needed:

```powershell
python -m pip install -r training-requirements.txt
```

## UVH-26 YOLO11 vehicle detector

UVH-26 is the only listed source currently verified as publicly downloadable
with a declared CC BY 4.0 dataset license. It provides 26,646 still images with
14 vehicle categories and a publisher train/validation split, but no test set,
pedestrian label, or separate motorcycle/scooter labels. The full image corpus
is a many-tens-of-gigabytes download. The downloader is opt-in and pins a
specific source revision. Review and comply with the dataset license before
running it.

```powershell
hf auth login
python -m training.download_uvh26 --split both --acknowledge-license
python -m training.prepare_uvh26 `
  --root ..\data\datasets\uvh26 `
  --output ..\data\prepared\uvh26 `
  --annotation-variant MV
```

The downloader uses Windows' trusted certificate store and limits transfer
concurrency by default. Hugging Face may rate-limit repeated anonymous access
(HTTP 429); authenticate with `hf auth login` using your own Hugging Face
account, then rerun the same download command to resume. Never paste an access
token into chat or commit it to the project. You can override concurrency with
`--max-workers 1` if throttling continues.

The converter verifies the publisher taxonomy and COCO boxes and hard-links
images by default (use `--link-mode copy` if hard links are not supported).
It writes a source/split report and does not invent pedestrian, separate
scooter, or separate motorcycle annotations. The initial local YOLO checkpoint
must be supplied by the operator and its license must permit this use:

Audit downloaded content with `--allow-incomplete` while the large transfer is
still running. The report identifies missing manifests/images and is marked
`incomplete`; after acquisition finishes, rerun without that flag for a full
annotation/image audit.

```powershell
python -m training.audit_datasets `
  --uvh26-root D:\NexSafeAI\datasets\uvh26 `
  --allow-incomplete `
  --output D:\NexSafeAI\datasets\uvh26-audit.json
```

```powershell
python -m training.train_detector `
  --data ..\data\prepared\uvh26\data.yaml `
  --base-weights ..\models\licensed-yolo11.pt `
  --config configs\detector_uvh26.json `
  --output ..\models\uvh26-yolo11.pt
```

Ultralytics uses the publisher validation split and records actual validation
precision, recall, mAP50, and mAP50-95 in a hash-bound
`*.pt.nexsafe.json` sidecar. UVH-26 has no held-out test data, so the sidecar
explicitly reports test metrics as unavailable. Copy the checkpoint and its
sidecar into the mounted model directory, then set `MODEL_WEIGHTS` to the
container path of the checkpoint. Backend status only displays metrics when
the sidecar hash matches the loaded file.

## Kaggle GPU training

The local Python environment has no PyTorch installation or CUDA device. Use
[`backend/notebooks/nexsafe_kaggle_gpu_training.ipynb`](../notebooks/nexsafe_kaggle_gpu_training.ipynb)
on Kaggle with a GPU accelerator and Internet enabled. Upload
`D:\NexSafeAI\nexsafe-source-smoke-20261103-v3.zip` as a private Kaggle Dataset named
`nexsafe-source`, attach it to the notebook, and run all cells. The notebook
uses the same pinned UVH-26 revision and defaults to an actual 400-image
training / 100-image validation smoke subset; it does not claim a held-out test
score because the source has no test split. Selected source images are cached
by dataset revision and subset configuration so interrupted/repeated runs can
reuse completed downloads instead of restarting a full dataset transfer.

The notebook requires you to review the Ultralytics checkpoint license and
explicitly confirm that review before training. ACCIDENT is optional, requires
Kaggle authorization, and is blocked unless its non-commercial/share-alike
terms or separate written permission are acknowledged. Its real accident
clips alone do not provide safe examples. Temporal and structured-risk
training run only when separately attached, owner-labeled, licensed, and
leakage-disjoint manifests/CSV splits meet the trainer requirements. No
training metrics or checkpoint exist until the Kaggle run completes and the
generated report is inspected.

The official [Ultralytics license page](https://www.ultralytics.com/license)
currently states that SaaS/API, private, proprietary, and commercial use needs
an Enterprise License unless the application is released in compliance with
AGPL-3.0. NexSafe's intended deployment may fall under those terms. Obtain
the appropriate license or commit to a compliant open-source release before
setting the notebook's license-review confirmation and training/deploying the
weights.

## Temporal accident detection / classification (CNN-LSTM)

Prepare manifests from the dataset owner's real video annotations. Each JSONL
record needs video path, source-video identity, real label, dataset, license,
and segment times; split by source video to prevent leakage:

```json
{"video":"videos/authorized-source.mp4","source_video_id":"source-camera-clip-001","start_seconds":12.0,"end_seconds":16.0,"label":"near_miss","dataset":"Authorized dataset name","license":"Exact dataset license","data_domain":"real"}
```

Supply separate train, validation, and test JSONL files, with every class in
each split and disjoint source video IDs and paths. The `data_domain` field
must be `real` or `synthetic`; the trainer rejects mixing domains in a run.
Only use collision labels present in the
source annotations. The trainer validates timing/provenance, records
per-epoch validation JSONL, selects the best validation macro-F1 checkpoint,
and evaluates that frozen checkpoint once on the held-out test split.

```powershell
python -m training.train_temporal `
  --train-manifest C:\datasets\nexsafe\train.jsonl `
  --validation-manifest C:\datasets\nexsafe\validation.jsonl `
  --test-manifest C:\datasets\nexsafe\test.jsonl `
  --dataset-name "Authorized dataset name" `
  --output C:\datasets\nexsafe\checkpoints\risk-cnnlstm.pt `
  --device auto
```

The model is a CNN spatial encoder plus LSTM over 16 frames sampled across a
4-second segment by default. The trainer refuses to assume 30 FPS if source
video timing is missing. This is a baseline temporal model, not an assurance
of real-world accident prediction. `ACCIDENT_MODEL_WEIGHTS` must point to a
resulting checkpoint; `ACCIDENT_RISK_CLASSES` must match explicitly labeled
classes. Set `ACCIDENT_ALERT_THRESHOLD` only after a separate calibration
process. Predictions are model outputs, never confirmed incidents.

## Structured road-risk model

The MLP accepts only explicitly selected numeric, pre-outcome feature columns
and an observed target column. It requires separate CSV train/validation/test
files and disjoint group IDs (for example a source region/time grouping),
target semantics, dataset name, and license. Weather forecasts or model-
generated risk scores are not ground-truth outcomes. Leakage control and
whether the chosen outcome is useful are responsibilities of the data owner;
review those assumptions before training.

```powershell
python -m training.train_structured_risk `
  --train-csv C:\datasets\risk\train.csv `
  --validation-csv C:\datasets\risk\validation.csv `
  --test-csv C:\datasets\risk\test.csv `
  --target observed_outcome `
  --group-column region_year `
  --features road_type_code,traffic_volume,rainfall_mm `
  --dataset-name "Authorized official dataset" `
  --label-definition "Exact observed outcome meaning" `
  --license "Exact source license" `
  --output C:\datasets\risk\road-risk.pt `
  --device auto
```

Configure `ROAD_RISK_MODEL_WEIGHTS` to the mounted checkpoint file. The
authenticated `POST /api/inference/road-risk` API accepts the checkpoint's
exact numeric feature names. Optionally configure
`ROAD_RISK_POSITIVE_CLASSES` with exact trained class names to obtain an
aggregated model probability; without it, `risk_score` is null, not guessed.

## Inference APIs and status

- `GET /api/model` reports loaded models, actual classes, versions, and metrics
  only when their checkpoints and metadata load successfully.
- `POST /api/inference/vehicle-detection` runs YOLO on an uploaded image.
- `POST /api/inference/vehicle-tracking` runs YOLO + ByteTrack on an uploaded
  video.
- `POST /api/inference/accident-detection` runs the configured temporal model
  on video with valid source FPS metadata.
- `POST /api/inference/road-risk` runs the configured structured model.
- `POST /api/videos/analyze` remains the combined authenticated upload flow.

All inference routes require authentication. An unavailable or untrained
checkpoint disables its task; the service does not ship mock weights,
predictions, metrics, or accident labels. Detection confidence is detector
confidence, not accident confidence.
