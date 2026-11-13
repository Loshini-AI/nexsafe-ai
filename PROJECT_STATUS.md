# NexSafe AI project status

**Audit date:** 2026-11-13
**Workspace:** `C:\Users\lokes\Desktop\accient`  
**Scope:** Initial audit plus subsequent implementation, GitHub publication,
and verification updates. See [PROJECT_AUDIT.md](./PROJECT_AUDIT.md) for the
current feature-by-feature audit and evidence.

## Current verification (2026-11-13)

- Published the existing source tree to
  `https://github.com/Loshini-AI/nexsafe-ai`; branch `main`. The initial
  publication commit was `e6dafa22c996cb722e1ca77b0ed27e6d383f89db`; latest
  previously published commit is `171bfad`. Local `.env`, databases, backups,
  datasets, model weights, Python virtual environments, and frontend
  build/dependency directories are ignored and were not committed.
- The project now includes `start-nexsafe.ps1`, project-local SQLite
  configuration fallback, SQLite online backups with integrity validation,
  and focused backup tests.
- Latest complete test run before the newest provider integration: **25 backend
  tests passed**; frontend type-check (`npm run check`) and production build
  (`npm run build`) passed.
- Live local health is HTTP 200 with SQLite available and process-local
  realtime fallback. The dashboard returns HTTP 200. CORS preflight from the
  local frontend origin is allowed.
- Live model endpoint reports detector, accident classifier, and structured
  road-risk model **unavailable** because no model weights are configured.
- Live dataset endpoint reports an incomplete UVH-26 split: **5,472** of
  **21,349** training images present, **15,877** missing, **no validation
  images**, and **2 image dimension mismatches**. The dataset labels support
  vehicle detection, not accident-risk training.
- Local dataset inventory is **10,953 files / 18,638,629,391 bytes** outside
  the repository on `D:`. It was not downloaded, copied, or modified during
  this work.
- The existing SQLite database on `D:` was preserved. Its project-local
  **90,112-byte** backup passed `PRAGMA integrity_check` and contains the
  application tables.
- Signup/account modifications were not performed against the actual database;
  auth tests use isolated SQLite test databases. Production PostgreSQL, Redis,
  external government credentials, configured cameras, and real model
  inference are not required for local startup and were not used.
- Profile/settings and admin-management pages, verified incident mapping, and
  production accessibility/security reviews remain incomplete. See the audit
  for feature statuses, test evidence, and prioritized requirements.

## Optional hosted object detection (2026-11-13)

- Added opt-in Hugging Face Inference Providers integration for generic
  `facebook/detr-resnet-50` object detection, using a backend-only
  `HF_INFERENCE_TOKEN`. Local inference remains the default. The hosted model
  does **not** classify accidents or predict road risk.
- Authenticated uploads require explicit privacy consent before images or a
  bounded set of sampled video frames is sent to Hugging Face. NexSafe removes
  temporary media and stores user-scoped analysis metadata/detections only.
  Video sampling is not continuous inference or tracking.
- Added authenticated `GET /api/analyses`, SQLite schema initialization, and
  Alembic migration `0004_analysis_history`. The current preserved user
  database was not changed.
- Verified: **32 backend tests passed**, frontend type-check and production
  build passed, Alembic history migration passed on a disposable SQLite
  database, and backend compile/dependency checks passed. Provider tests use
  mocked HTTP responses; live Hugging Face inference is unverified because no
  token is configured. No external media was transmitted.
- Hugging Face Inference Providers may be paid; free accounts do not include
  inference credits. Review provider terms and pricing before enabling it.
  Configuration and limitations are documented in the root README and
  `.env.example`.

## Continued implementation (2026-11-03)

### Signup investigation and fix

- The shared frontend was reachable at `127.0.0.1:3000`, while browser requests
  to `localhost:8000` failed with `ERR_CONNECTION_REFUSED`. The API health and
  registration endpoints were unreachable, and nothing was listening on local
  PostgreSQL (`5432`) or Redis (`6379`). This is the verified cause of the
  current live signup failure: the backend/data services are not running, not
  an external identity-provider rejection.
- NexSafe uses its own FastAPI/PostgreSQL account store and JWT tokens; no
  external authentication provider is configured.
- The previous frontend displayed signup without checking if registration or
  the API was available. It now queries `/api/auth/registration`, disables
  submission when signup is unavailable, shows a retry/action message, and
  converts an API connection failure into a clear service-start instruction.
- The browser is currently served from `127.0.0.1`, but the former default CORS
  origin allowed only `localhost`. CORS now accepts the comma-separated
  `FRONTEND_ORIGIN` allowlist, and the sample local configuration includes
  both hostnames.
- Compose now builds its default database URL from `POSTGRES_USER` and
  `POSTGRES_DB` rather than silently hard-coding them. Use URL-safe characters
  for `POSTGRES_PASSWORD`, or set a percent-encoded `DATABASE_URL`.
- Added API integration tests using an isolated in-memory SQLite database:
  first-account admin creation and login, duplicate handling, closed public
  registration, and localhost/loopback CORS all pass. This verifies account
  route behavior, but it does **not** substitute for a signup against the
  currently unavailable PostgreSQL service.
- A production frontend smoke check against the unconfigured API verified that
  the signup page now displays the unavailable-service explanation and keeps
  account submission disabled instead of sending a doomed request.

### Windows backend setup and dependencies

- Added `backend\setup-windows.ps1`, which creates a separate Python 3.11
  environment at `.venv-backend311`, installs API/test dependencies, checks
  pip consistency, imports the API, and runs its tests. The original Python
  3.14 `.venv` was left unchanged.
- Split the optional inference/training dependencies into
  `backend\vision-requirements.txt`; base API setup does not install PyTorch,
  CUDA, or Ultralytics. Docker and training requirements continue to include
  the vision stack. The structured-risk module now imports Torch only when a
  checkpoint is configured, so the API can start without model packages.
- The new Python 3.11 environment installed the declared API/test packages;
  `pip check`, API imports, and **13 backend tests passed**. PyTorch and
  Ultralytics are absent from this environment as intended.
- Backend configuration now discovers the project-root `.env` when launching
  from the `backend` directory. No real `.env` or database service is present
  here, so migration/API startup against PostgreSQL remains unverified.

### First vehicle-model training readiness

- The Kaggle notebook and pipeline now default to **400 train / 100 publisher
  validation images, 5 epochs, batch 4, image size 640**. They download only
  selected images from the pinned UVH-26 revision and cache them by selection
  fingerprint, so the same selection can reuse completed files after a
  restarted/interrupted run. The existing 18.64 GB partial local dataset was
  not copied, modified, or expanded.
- The pipeline rejects source-image/COCO dimension mismatches, reads actual
  training losses from YOLO's `results.csv`, records the pretrained
  checkpoint hash and validation metrics, reloads the best checkpoint, and
  runs a real inference pass on a publisher-validation image before reporting
  completion.
- The frontend now has an authenticated image-upload path through
  `/api/inference/vehicle-detection`, displays actual returned bounding boxes,
  labels, confidence and latency, and reports unavailable-model errors without
  inventing detections. The API returns original image dimensions for the
  overlay. Model status exposes saved training-loss metrics as well as
  validation metrics.
- Created and ZIP-verified
  `D:\NexSafeAI\nexsafe-source-smoke-20261103-v3.zip` (37 source files,
  70,880 bytes), with no dataset media or credentials.
- **Training has not run. No checkpoint, evaluation metrics, or real-image
  model inference result exists yet.** The notebook's Ultralytics license gate
  remains disabled. Its official license page says private/proprietary,
  commercial, and SaaS/API use needs an Enterprise License unless the project
  is released in AGPL-3.0 compliance.
- To proceed, manually sign in to Kaggle, create a private dataset containing
  the v3 source ZIP, attach it to the notebook, enable Internet and a GPU,
  restart the session, and run all cells. For any proprietary/commercial
  NexSafe deployment, obtain Ultralytics' Enterprise License before changing
  the notebook's license confirmation. UVH-26 access is public; Kaggle API
  secrets are not needed for this vehicle experiment. If Hugging Face returns
  429, revoke the previously exposed token and add a replacement only as a
  Kaggle Secret named `HF_TOKEN`.

## Executive summary

NexSafe AI is an existing Next.js/React/TypeScript frontend and FastAPI backend,
with PostgreSQL/Alembic persistence, Redis-backed WebSocket events, and
conditional computer-vision/model services. It has a functioning application
structure and honest unavailable/empty states; it is not a blank website or a
trained accident-detection system.

The frontend passes TypeScript checking and a Next.js production build. The
new Python 3.11 API/test environment passes imports and dependency checks, and
all 13 backend unit/integration tests pass. However, Docker is unavailable, no
`.env` or PostgreSQL/Redis service exists, and the configured API cannot be
started against its intended services in this environment. No trained model
checkpoint was found in the application tree.

The UVH-26 copy is external to the application at
`D:\NexSafeAI\datasets\uvh26`. It is incomplete: the audit found 5,472 PNGs,
only from the publisher's training split, while 15,877 annotated training
images are absent and the validation split is not downloaded. Two downloaded
images have dimensions that disagree with their COCO records. No model was
trained.

## Existing architecture

| Area | Existing implementation | Current boundary |
|---|---|---|
| Frontend | Next.js 16 App Router, React 19, TypeScript, Tailwind CSS, Framer Motion, Leaflet/OpenStreetMap. Main pages are the public landing page and dashboard. | The dashboard is implemented in a single large client component. It has sign-in/create-account, read-only preview, overview, monitoring, alerts, map, analytics, model, and government-data views. |
| API | FastAPI in `backend/app/main.py`; request schemas in `schemas.py`; OpenAPI docs are available when the service runs. | Account API routes were tested in-process with SQLite. Runtime against the intended PostgreSQL/Redis stack remains blocked because those services are not running. |
| Persistence | Async SQLAlchemy + PostgreSQL; Alembic has initial and government-data migrations. Models include users, cameras, events, inference measurements, and cached government snapshots. | No database instance or migration run was available for this audit. |
| Authentication | Password hashing, bearer JWT authentication, account registration and first-user administrator bootstrap. Registration is disabled after initial setup unless explicitly enabled. | Browser access tokens are stored in local storage; the WebSocket endpoint accepts the token in the URL query string. Review token transport/storage before an internet-facing deployment. |
| Real-time | Redis pub/sub relays camera frames, camera status, risk predictions, and event updates to authenticated WebSocket subscribers. | Redis and camera-stream integration were not runtime-tested. |
| Cameras and video | Camera sources are encrypted before storage; hostname allowlisting is required for URL sources. OpenCV reads uploads and live sources; Ultralytics performs detector inference and ByteTrack tracking when model weights load. | No real camera, configured checkpoint, or end-to-end video test was available. A detector alone is not an accident classifier. |
| Government data | Modular IMD, OGD/MoRTH, and institution-authorized iRAD services store provider snapshots and their source/sync timestamps. Open-Meteo is queried for supplied coordinates. | IMD/OGD/iRAD credentials and identifiers are not configured in a local `.env`; provider connectivity was not verified. Weather is context only and is not an input to the current visual model. |
| AI/ML | Existing YOLO11 preparation/training, CNN-LSTM temporal training, structured-risk training, checkpoint loading, and evaluation metadata paths. | All three model services require actual checkpoints. No checkpoint is present; accident and structured-risk model predictions are unavailable. |
| Deployment | Docker Compose describes PostgreSQL, Redis, FastAPI, and Next.js; the API container applies Alembic migrations on startup. | Docker CLI is not installed/on PATH. `.env` must be created and configured before Compose can start. |

## What is already working (verified from source or commands)

- The frontend requests backend records rather than supplying seeded dashboard
  statistics. Empty, insufficient-data, unavailable-service, disconnected
  camera, and unloaded-model states are present.
- The public hero is an original, explicitly labeled local visualization; it
  is not presented as live CCTV.
- Dashboard APIs cover account registration/login, cameras, camera
  start/stop, image detection, video tracking/analysis, temporal accident
  inference, structured road-risk inference, events, analytics, system
  metrics, weather, government data, model status, and WebSockets.
- Camera status and inference measurements are tied to live workers and saved
  inference records. Camera locations on the map come from registered
  coordinates. Analytics return an insufficient-data state below the
  configured minimum rather than manufacturing chart series.
- Model status only exposes detector evaluation metadata when the sidecar's
  checkpoint hash matches. Temporal and structured model loaders require
  provenance/evaluation metadata.
- Authenticated image detection and live-frame detections are connected to the
  frontend; uploads remain disabled until a real detector checkpoint is
  configured.
- Training utilities enforce publisher train/validation splits, dataset
  taxonomy and annotation validation, temporal source-video-disjoint splits,
  separate real/synthetic domains, and observed outcomes for structured risk.
- `npm run check`: **passed** (`tsc --noEmit`).
- `npm run build`: **passed** (Next.js 16.4.3; `/` and `/dashboard` generated).
- `backend\setup-windows.ps1`: **passed**; created the Python 3.11 API/test
  environment, verified imports and dependencies, and ran all tests.
- `python -m unittest discover -s tests -p 'test_*.py' -v` in
  `.venv-backend311`: **13 passed**, including isolated database-backed signup.
- `pip check`: **passed**.
- `python -m compileall -q backend\app backend\training backend\tests
  backend\migrations`: **passed** after final backend/model changes.
- Kaggle notebook JSON and the v3 source archive: **validated**. Kaggle GPU
  training itself: **not run**.

## Incomplete, unavailable, or needing follow-up

### Runtime and deployment

- There is no root `.env`; `.env.example` contains placeholder secrets.
- The existing `.venv` is Python 3.14.6 and still lacks backend packages. Use
  `.venv-backend311` for API setup and tests. The latter intentionally has no
  PyTorch/Ultralytics; install the vision requirements only in a compatible
  deployment/training environment.
- Docker Compose could not be exercised because the Docker CLI is unavailable.
- PostgreSQL migrations, Redis/WebSockets, live cameras, and real model
  inference have not been tested end-to-end. Signup route tests use SQLite and
  do not prove the configured PostgreSQL service is running.
- No trained `.pt`, `.pth`, `.onnx`, or engine checkpoint was found in the
  application workspace. Detector, temporal classifier, and structured-risk
  prediction therefore remain disabled until real checkpoints are supplied.
- The dashboard is concentrated in `frontend/src/components/Dashboard.tsx`.
  The map currently shows registered camera locations only; incident markers,
  risk zones, and additional analytics dimensions are not implemented. Account
  profile management, alert assignment UI, evidence snapshots/clips, and
  email/SMS delivery are also not present.

### Dataset and training

- Current local data was measured at **10,953 files / 18,638,629,391 bytes
  (~18.64 GB)**, including **5,472 PNGs / 18,518,069,240 bytes**. It lives
  outside the application tree on `D:` and should not be copied into a second
  project directory.
- The refreshed audit at `D:\NexSafeAI\datasets\uvh26-audit.json` reports
  **incomplete**. The pinned training COCO annotation contains 21,349 image
  records and 252,723 boxes; 5,472 images are currently present and 15,877
  annotated training images are missing. The validation annotation/images are
  absent.
- Two downloaded files (`22876.png`, `163302.png`) have PNG dimensions
  **1620×1080**, while the COCO records say **1920×1080**. The audit records
  these mismatches. Do not train on or silently resize/relabel these records
  without verifying the source files/annotations.
- The expected full PNG payload is about **89.84 GB**. The interrupted
  acquisition should not be restarted as a full download by default. First
  decide whether to resume the full corpus or use the existing bounded
  selection path in the Kaggle GPU pipeline.
- UVH-26 supplies still images and 14 vehicle categories; it does not supply
  pedestrian labels, separate motorcycle/scooter labels, accident-video
  sequences, or a held-out test split.
- ACCIDENT is documented in the source catalog with current Kaggle metadata
  license **CC BY-NC-SA 4.0**. Non-commercial research/share-alike use was
  confirmed in conversation. It must not be used commercially without
  separate written permission. Its real accident clips alone do not provide
  verified safe-video examples. No ACCIDENT/IDD media was downloaded.
- Kaggle GPU training requires a Kaggle notebook session, GPU/Internet, the
  source package, reviewed Ultralytics checkpoint terms, and any source data
  and labels needed for the chosen task. The notebook has not been run; there
  are no measured training/evaluation results.

### Documentation and security notes

- `backend/datasets/README.md` still says ACCIDENT has no Kaggle license
  metadata; that is stale compared with the checked dataset catalog and needs
  synchronization.
- The root `README.md` still says no dataset was downloaded. That is stale for
  the current machine's partial external UVH-26 copy, although dataset media is
  not bundled in the application folder.
- A Hugging Face credential file was detected in the user profile during
  inspection. A token value was previously pasted into chat. Revoke that
  exposed token in Hugging Face, then create a replacement and keep it only in
  the local credential store/Kaggle Secrets. No token value is included here
  or in the project report.
- `CAMERA_ALLOWED_HOSTS` is a host allowlist, not a full network-egress
  boundary. Before untrusted users can register cameras, add deployment-level
  SSRF protections (including resolved-address/private-network restrictions)
  and review credential-bearing source handling.
- The backend currently has no rate limiting or security integration tests
  for authentication, upload limits, camera-source validation, or WebSocket
  authorization. Treat the Compose setup as a single-host development starting
  point, not an internet-facing deployment.

## Prioritized development plan

1. **Credential safety and local environment:** revoke the exposed Hugging Face
   token; set up a clean local Python environment from the checked-in
   requirements; create `.env` from `.env.example` with unique strong secrets.
   Do not add credentials to source control or chat.
2. **Dataset integrity and storage control:** retain the current `D:` copy;
   decide between resuming it and acquiring only the deterministic training
   subset needed for Kaggle. Investigate both dimension mismatches against the
   pinned source. Refresh the audit after any authorized acquisition. Do not
   delete the existing partial data.
3. **First model experiment:** after a verified train/validation subset and
   licensed pretrained weights are attached, run the Kaggle notebook's
   bounded YOLO11 training; archive its checkpoint, hash-bound sidecar, and
   actual validation report. Do not call validation metrics test metrics.
4. **Backend runtime/API validation:** once dependencies and PostgreSQL/Redis
   are available, run migrations, health/auth/API tests, and a real image/video
   inference smoke test with the trained checkpoint.
5. **Temporal/structured models:** proceed only after obtaining appropriately
   licensed owner-annotated data with valid labels, provenance, source/group-
   disjoint train/validation/test splits, and sufficient examples.
6. **Production hardening and UI completion:** add focused backend/API/security
   tests, token transport improvements, SSRF protections, and complete
   prioritized product gaps (map events, alert assignment/evidence, account
   profile, and notification integrations) without replacing the existing
   design.

## Work completed for this audit

Created this report after source/configuration review and validation. The
UVH-26 converter now checks each image's actual dimensions against its COCO
record before creating labels, with a regression test for mismatches. No model
training, new dataset download, credential use, or application redesign was
performed during this audit.
