# NexSafe AI

**Predict. Protect. Prevent.**

NexSafe AI is a self-hosted road-safety monitoring platform. Camera records,
events, service health, and analytics come from configured services and stored
records. The application does not ship demo records, model weights, or
simulated camera feeds.

## Run locally (SQLite, no Docker)

The local API stores users and login sessions in
`D:\NexSafeAI\data\nexsafe.db` when that existing database is present; otherwise
it uses `data\nexsafe.db` in this project. It creates the database directory
and SQLite tables automatically at startup. Local account registration, login,
and logout do not require PostgreSQL or Redis. Passwords are Argon2 hashes;
bearer access tokens are persisted as revocable sessions in SQLite.

For a one-command Windows launch, run this from the project directory:

```powershell
.\start-nexsafe.ps1
```

The launcher creates a private local `.env` with independent random secrets
only when one does not already exist, prepares missing Python/Node dependencies,
chooses free local ports if 8000 or 3000 are occupied, then checks the SQLite
health endpoint and dashboard before opening the site. Logs are written to
`%LOCALAPPDATA%\NexSafeAI\logs`. Existing `.env`, databases, datasets, and
model files are left untouched. If Python 3.11 or Node.js is unavailable, the
launcher reports the missing runtime instead of substituting simulated data.
Before starting, it also creates or verifies a daily SQLite online backup in
`data\backups` and stores local uploads under `data\uploads`, regardless of a
container-only upload path in `.env`. SQLite's online-backup API makes a
consistent snapshot while the database is running. Backups contain account
hashes and application records, so keep the project data directory private.

To run the services manually instead:

```powershell
Set-Location C:\Users\<you>\Desktop\accient
.\backend\setup-windows.ps1
Set-Location .\backend
..\.venv-backend311\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another PowerShell window, run the existing frontend:

```powershell
Set-Location C:\Users\<you>\Desktop\accient\frontend
npm run dev -- --hostname 127.0.0.1
```

Open `http://localhost:3000/dashboard` and choose **Create account**. Provide
your own name, email, password, and confirmation; no demo users are created.
The first account is the administrator. To allow later registrations, set
`ALLOW_REGISTRATION=true` in `.env` and restart the API. The SQLite database
file persists across backend restarts; daily verified backups are stored in
`data\backups`.

The API is available at `http://127.0.0.1:8000`; its health endpoint is
`http://127.0.0.1:8000/api/health`. PostgreSQL and Redis remain optional
infrastructure for container deployments and real-time multi-process
broadcasting; they are not needed for local account creation or login.

The local `FRONTEND_ORIGIN` setting accepts a comma-separated allowlist. Keep
only the exact frontend origins you use in production. The supplied local
configuration permits both `localhost:3000` and `127.0.0.1:3000`. The local
SQLite setup does not use PostgreSQL or Redis environment settings.

The first-user bootstrap takes a SQLite write lock so concurrent sign-ups
cannot both claim the initial administrator. Additional accounts require
`ALLOW_REGISTRATION=true`; keep public registration disabled in production.
Choose your own email and password (at least 12 characters, including at least
three of lowercase letters, uppercase letters, numbers, and symbols) in the
dashboard's account form; no default credentials are created or shipped.

PostgreSQL is used by the container deployment. Redis is optional for local,
single-process operation, which uses an in-memory real-time event bus; Redis
enables broadcasts across multiple API processes.
The API applies the checked-in Alembic migration on container startup. Do not
expose the API or Redis directly to the public internet.

## Real data and model configuration

- Register cameras through `POST /api/cameras`. Camera source credentials are
  not returned by the API. Only authorized, reachable feeds can be processed.
- A video upload is analyzed only if an actual Ultralytics YOLO weights file
  is configured with `MODEL_WEIGHTS`. If weights are absent or cannot load,
  the API reports `AI MODEL UNAVAILABLE — INFERENCE DISABLED.` and does not
  produce predictions.
- Set `MODEL_WEIGHTS=/models/your-weights.pt` and `MODEL_WEIGHTS_HOST` to the
  host directory containing your weights file. The mounted directory is read-only.
- Set independent, long random values for `JWT_SECRET` and
  `CAMERA_ENCRYPTION_KEY`; camera stream sources are encrypted before storage.
  Keep the encryption key stable and backed up or existing credentials cannot
  be decrypted by a future ingestion worker.
- Add each authorized stream hostname to `CAMERA_ALLOWED_HOSTS` as a
  comma-separated allowlist. Device-index webcams do not use this allowlist.
- A configured YOLO model provides object detections only. It is not an
  accident classifier. Accident-risk prediction stays disabled until a
  temporal model has been trained and validated using the included pipeline
  and real labeled video, then configured as `ACCIDENT_MODEL_WEIGHTS`.
- The optional structured road-risk model is configured separately with
  `ROAD_RISK_MODEL_WEIGHTS`. Its predictions are disabled until trained with
  actual labeled records, leakage-safe splits, verified provenance, and a
  held-out test set. Set `ROAD_RISK_POSITIVE_CLASSES` only to class names
  present in that checkpoint; otherwise no aggregated risk score is returned.
- With a loaded model, the stream worker can read an authorized webcam or
  RTSP/HTTP-compatible stream and publish actual annotated frame detections
  and ByteTrack IDs. Each active stream owns a tracker model instance. A stream
  that cannot be opened is reported disconnected. Detection is not an accident
  alert or risk score.
- A configured, validated CNN-LSTM checkpoint evaluates temporal frame
  sequences from streams and uploaded videos. Any emitted score is a model
  probability over the configured risk classes—not a confirmed crash. Live
  persistent alerts require an explicitly configured, calibrated
  `ACCIDENT_ALERT_THRESHOLD`.
- Optical flow is real image-space pixel-motion telemetry only. Time-to-
  collision in physical units is not shown because no camera calibration,
  scene geometry, or metric distance source is configured.
- The weather endpoint queries Open-Meteo for caller-supplied coordinates and
  labels the provider. Weather is not used to fabricate risk scores.
- Government data integrations are optional and fail closed. Configure the
  issued `IMD_API_KEY`, its exact `IMD_AUTH_HEADER` and optional
  `IMD_AUTH_SCHEME` from the account's IMD instructions, official
  `IMD_STATION_IDS`, and, if available for your
  account, `IMD_CITY_IDS` and `IMD_WARNINGS_URL`. IMD observations come from
  the [official IMD API reference](https://api.imd.gov.in/public/api_reference.html),
  including its documented `current_wx` endpoint, and retain the station's UTC
  observation time. Forecasts are separately labeled; warnings require an
  endpoint documented for the authorized account. The IMD portal currently
  requires authenticated access.
- Configure `OGD_API_KEY` and `MORTH_OGD_RESOURCE_ID` with the resource UUID
  from the official OGD catalog for a MoRTH road-accident dataset. NexSafe
  checks the returned resource metadata for MoRTH/road-accident attribution
  before saving it. The API fetches at most 5,000 actual records and preserves
  the source metadata, reporting years, and last successful sync. MoRTH data
  is historical, not a live accident feed. OGD resources may require an
  account API key.
- Additional OGD resources can be enabled with `OGD_RESOURCE_IDS` (comma-
  separated catalog UUIDs). Their returned catalog metadata and records are
  displayed as provider data; verify each resource's owner and license in the
  official catalog before enabling it.
- iRAD is role-restricted and no public data API was found in the official
  portal. Do not scrape it or reuse browser credentials. An authorized
  institution may configure `IRAD_API_URL` and `IRAD_API_TOKEN` only for an
  official HTTPS `parivahan.gov.in` endpoint provided by its data owner. The
  connector reports endpoint availability and record count without copying
  accident-level records into the shared application database.
- Government snapshots are stored in PostgreSQL. When a provider fails, the
  API retains its last verified payload and original observation/publication
  timestamp and marks it stale. `GOVERNMENT_DATA_REFRESH_SECONDS` controls
  the provider polling interval (60–86,400 seconds). Credentials stay on the
  backend and are not sent to the browser.
- Cameras can be linked to an official IMD station ID. A fresh station
  observation is attached to temporal predictions as **context only**; the
  existing visual CNN-LSTM was not trained with weather inputs, so weather
  does not alter its prediction score. A multimodal model requires a separate
  labeled dataset, training, and validation before it can consume weather.
- Analytics are computed from persisted events and return insufficient-data
  states when there are not enough records.
- `backend/training/README.md` documents the manifest format and training
  command for real, lawfully obtained, annotated video. No DAD/DoTA/CADP
  dataset or trained accident checkpoint is bundled. Until a trained,
  validated CNN-LSTM checkpoint is configured, temporal risk prediction stays
  disabled. Configure `ACCIDENT_ALERT_THRESHOLD` only after selecting and
  calibrating a threshold against held-out data; without it, predictions may
  be observed but no risk alert is persisted.

See the [project status report](./PROJECT_STATUS.md), [model-training
guide](./backend/training/README.md), the [Kaggle GPU
notebook](./backend/notebooks/nexsafe_kaggle_gpu_training.ipynb), and [dataset
access/license status](./backend/datasets/catalog.json). Dataset media is not
bundled with the application; the current local UVH-26 acquisition and audit
status are recorded in the project status report. Protect credentials, uploaded
videos, database backups, and logs according to your organization's retention
policy.
For internet-facing deployments, terminate TLS at a trusted reverse proxy,
restrict network access to the API, configure `FRONTEND_ORIGIN` and
`NEXT_PUBLIC_API_URL` for the deployment hostname, and use managed/rotated
secrets. The supplied Compose file is a single-host starting point, not a
multi-node high-availability deployment.

## API outline

- `POST /api/auth/register`, `POST /api/auth/token`
- `GET|POST /api/cameras`, `DELETE /api/cameras/{camera_id}`
- `POST /api/cameras/{camera_id}/start`, `POST /api/cameras/{camera_id}/stop`
- `POST /api/videos/analyze` (authenticated multipart upload)
- `POST /api/inference/vehicle-detection` (authenticated image inference)
- `POST /api/inference/vehicle-tracking` (authenticated video + ByteTrack)
- `POST /api/inference/accident-detection` (authenticated temporal video model)
- `POST /api/inference/road-risk` (authenticated structured model)
- `GET /api/events`, `PATCH /api/events/{event_id}`
- `GET /api/analytics`, `GET /api/health`, `GET /api/model`
- `GET /api/datasets/status` (latest local dataset audit and source-label scope)
- `POST /api/auth/register`, `POST /api/auth/token`, `POST /api/auth/logout`
- `GET /api/weather?latitude=...&longitude=...`
- `GET /api/government`, `POST /api/government/refresh`
- `WS /api/ws` (authenticated with an access token query parameter)

The browser UI is a monitoring shell with honest empty states. Camera ingestion
is started per registered camera. YOLO video detections require configured
weights; temporal risk predictions additionally require a separately trained
and validated CNN-LSTM checkpoint. No accident checkpoint or third-party
dataset is included.
The model center reads the latest UVH-26 audit from `DATASET_AUDIT_PATH` and
displays the observed split counts and audit status. Vehicle-detection labels
are not accident-risk labels; missing datasets, model checkpoints, or
evaluation metrics are reported as unavailable rather than inferred.

See [`backend/training/README.md`](./backend/training/README.md) for training
commands and [`backend/datasets/catalog.json`](./backend/datasets/catalog.json)
for verified dataset access and license limits. The application does not
bundle dataset media or trained checkpoints. Current local acquisition,
validation, and training results (if any) are tracked in
[`PROJECT_STATUS.md`](./PROJECT_STATUS.md).
