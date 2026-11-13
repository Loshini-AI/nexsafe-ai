# NexSafe AI project audit

**Audit date:** 2026-11-13  
**Workspace:** `C:\Users\lokes\Desktop\accient`  
**Repository:** `Loshini-AI/nexsafe-ai`, branch `main`  
**Audit scope:** Existing source, configuration, local dataset/model inventory,
live local health/model/dataset/frontend endpoints, and the automated
verification runs listed below. No account, dataset, or model was created or
changed during the audit.

The Git history available at the start of this audit contained one initial
project commit (`e6dafa2`); there was no earlier repository history to compare.
The application has optional Docker Compose/container files, but local
development startup uses the Windows launcher and SQLite and does not require
or invoke Docker, PostgreSQL, or Redis.

## Summary

NexSafe is an existing Next.js 16 / React 19 / TypeScript frontend and FastAPI
backend. The local backend and dashboard respond successfully, SQLite-backed
startup and authentication are covered by isolated integration tests, and the
application distinguishes unavailable model inference from real results.
This is a functioning development application, not yet a complete,
production-ready accident-prediction service.

| Area | Status | Evidence and limitations |
|---|---|---|
| Landing page | PARTIALLY COMPLETED | Next.js landing route is implemented and part of the production build. Full browser accessibility/responsive testing was not run in this audit. |
| Authentication | COMPLETED (tested API flow) | Registration bootstrap, Argon2 password hashing, login, protected route, revocation, and failure cases are covered by the backend tests. The first registered user becomes admin, but there are no admin-only management routes. |
| Local SQLite database | COMPLETED (local runtime) | Live health reports SQLite available. SQLAlchemy creates tables at startup; file-backed persistence and table initialization are covered by backend tests. The configured existing database is `D:\NexSafeAI\data\nexsafe.db`; it was preserved. |
| Cameras and ownership | PARTIALLY COMPLETED | Authenticated camera CRUD/start/stop APIs are implemented with ownership checks and encrypted sources. Live camera operation was not exercised; a configured detector checkpoint is absent. |
| Image/video detection | PARTIALLY COMPLETED | Upload endpoints validate supported types and size limits and fail closed when checkpoints are unavailable. Real model inference could not be exercised because no checkpoint is configured. |
| Accident/temporal predictions | NOT AVAILABLE | CNN-LSTM code exists, but no validated checkpoint is configured. The live model endpoint reports the classifier unavailable. |
| Structured road-risk predictions | NOT AVAILABLE | Training/loading/inference code exists, but no trained checkpoint is configured. The live model endpoint reports the model unavailable. |
| Analytics and dashboard data | PARTIALLY COMPLETED | Authenticated APIs aggregate persisted events/frames and report insufficient data instead of fabricating charts. There is no live verified accident feed. |
| Geographic map | PARTIALLY COMPLETED | Leaflet renders registered camera locations with coordinates. Verified incident geocoding, hotspot clustering, location search, and date/state/district filters are not implemented. |
| Real-time monitoring | PARTIALLY COMPLETED | The backend has authenticated WebSocket events and a process-local fallback when Redis is absent. No live camera stream was available to test. |
| Government/weather integrations | PARTIALLY COMPLETED | Optional provider connectors exist. IMD/OGD/iRAD credentials, identifiers, and authorized endpoints are not configured, so actual government data delivery was not verified. Weather uses a caller-supplied-coordinate provider request. |
| Dataset management | PARTIALLY COMPLETED | Catalog, pinned-revision UVH-26 preparation, resumable download, and audit tools exist. The local UVH-26 audit is incomplete; the management interface is status-oriented rather than a full download/repair console. |
| Dataset integrity | PARTIALLY COMPLETED | Live audit reports 5,472/21,349 training images, 15,877 missing, no validation images, and two dimension mismatches. Dataset root is external at `D:\NexSafeAI\datasets\uvh26`. No duplicate/corruption-wide fresh scan was run. |
| Model center | PARTIALLY COMPLETED | API/UI expose detector, temporal and structured model status and available provenance/metrics. Training controls, artifact lifecycle, and a trained model are absent. |
| Prediction history | PARTIALLY COMPLETED | Event history and image/video inference records exist in the backend schema/services. A complete user-facing saved-analysis history, export, and profile-linked UX are not implemented. |
| User profile/settings | NOT IMPLEMENTED | No profile read/update/password-change/settings API or corresponding page is present. |
| Admin dashboard | NOT IMPLEMENTED | Initial-admin role assignment exists. There are no admin authorization dependencies or admin-management APIs/pages. |
| Backup | COMPLETED (verified SQLite backup) | `backend/app/backup.py` uses SQLite online backup and verifies integrity; unit tests cover snapshot reuse and missing/non-SQLite databases. |
| Windows launcher | PARTIALLY COMPLETED | `start-nexsafe.ps1` prepares local startup and checks readiness. This audit adds reuse of existing healthy NexSafe API and frontend processes; process supervision after launcher exit remains outside its scope. The updated launcher parsed successfully and was run against already healthy local services without creating another instance. |
| Security | PARTIALLY COMPLETED | Argon2 hashing, signed expiring/revocable JWTs, ownership checks, camera-source hostname allowlisting, secret encryption and conservative inference behavior are implemented. Browser tokens use localStorage and are sent in the WebSocket query string; rate limiting, deployment-level SSRF/network egress controls, and a dedicated security test suite remain unimplemented. |
| Accessibility/responsiveness | NEEDS VERIFICATION | Responsive utility classes, labels, and selected ARIA states exist. No systematic keyboard, screen-reader, contrast, or viewport test was run. |
| Production/deployment readiness | NOT READY | Development frontend build succeeds, but external credentials/feeds and all model checkpoints are absent; deployment security and production hosting were not verified. Docker files are retained for existing compatibility, but the local launcher uses SQLite without Docker. |

## Architecture and data flow

- **Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS, Framer
  Motion, Lucide, and React-Leaflet. The principal dashboard is a large client
  component in `frontend/src/components/Dashboard.tsx`; the map is
  `frontend/src/components/MapView.tsx`.
- **API:** FastAPI routes and application lifecycle in
  `backend/app/main.py`; Pydantic request/response definitions in
  `backend/app/schemas.py`.
- **Database:** SQLAlchemy async models in `backend/app/models.py`. Local
  configuration uses `sqlite+aiosqlite`; SQLAlchemy metadata initialization
  creates missing tables. The API has Alembic migration files. No schema
  migration upgrade was applied to the preserved existing user database as
  part of this audit.
- **Authentication:** Argon2 password hashes and HS256 bearer tokens with
  persisted revocable `UserSession` rows. The first account is an administrator;
  subsequent registrations require `ALLOW_REGISTRATION=true`.
- **Realtime:** Redis pub/sub when reachable; otherwise a process-local,
  bounded event bus. The health endpoint reports the active mode.
- **ML:** Optional YOLO object detection, CNN-LSTM temporal risk, and structured
  risk pipelines. The APIs deliberately return unavailable/503 until their
  actual compatible checkpoints and verified metadata are configured.
- **External data:** Optional Open-Meteo and configured government connectors.
  Live credentials/authorized resource IDs are not supplied by the code audit.

## API surfaces found

`/api/health`, `/api/model`, `/api/datasets/status`, authentication
registration/status/token/logout, camera list/create/delete/start/stop, video
analysis/tracking, vehicle image detection, temporal accident detection,
structured road risk, event list/update, overview, analytics, system metrics,
weather, government snapshots/refresh, and `/api/ws`.

The APIs for health, model state, dataset state, authentication flows,
dashboard/analytics behavior, and unavailable-model handling have unit or live
smoke coverage. No real camera, configured government feed, or model-backed
inference was available to verify end to end.

## Local data and model inventory

- UVH-26 dataset files: **10,953 files / 18,638,629,391 bytes** on `D:`.
- Current API audit: training **5,472 available / 21,349 annotated**, **15,877
  missing**, **252,723 annotations**, **2 dimension mismatches**; validation
  images are absent. Dataset labels support vehicle detection, not accident
  classification or temporal prediction.
- No model checkpoint is configured at runtime: detector, accident classifier,
  and structured-risk model endpoints all report `unavailable`.
- SQLite database at `D:\NexSafeAI\data\nexsafe.db` exists. The local application
  backup at `data\backups\nexsafe-20261113.db` passed SQLite integrity check
  and contained the application tables.
- No credentials, real account data, database backups, downloaded media, or
  model weights are included in Git.

## Verification run

| Check | Result |
|---|---|
| Backend unit/integration suite, `python -m unittest discover -s tests -p "test_*.py" -v` | **25 passed** (2026-11-13); includes auth, dashboard/analytics, dataset tools, and three SQLite-backup tests. |
| Frontend `npm run check` | **Passed** (`tsc --noEmit`). |
| Frontend `npm run build` | **Passed**; Next.js generated `/`, `/_not-found`, and `/dashboard`. |
| Backend `pip check` | **Passed**; no broken requirements reported. |
| Windows launcher parser check | **Passed** after launcher update. |
| Live `/api/health` | **200**; database available, realtime process-local. |
| Live `/api/model` | **200**; all three models correctly unavailable without weights. |
| Live `/api/datasets/status` | **200**; incomplete UVH-26 audit as detailed above. |
| Live `/dashboard` | **200**. |
| CORS preflight from `127.0.0.1:3000` | **Allowed** by the local API. |
| Repeated Windows launcher invocation | **Passed**; reused the existing API on port 8000 and frontend on port 3000 and reported both without spawning duplicates. |
| Live model inference / trained checkpoint | **Not run**; none is configured. |
| Real dataset acquisition/training | **Not run**; source data is incomplete and no compatible model weights/training hardware session was provided. |
| Live registration/account changes | **Not performed**; registration is disabled after first-user bootstrap. Auth was tested against isolated SQLite databases. |
| Desktop/mobile/browser accessibility | **Not run** beyond the local dashboard HTTP smoke check. |

## Prioritized remaining work

1. **Acquire and validate model-training inputs.** Preserve the partial UVH-26
   copy; resolve its two dimension mismatches against source records and obtain
   the missing publisher validation split before detector training. UVH-26
   cannot train an accident-risk classifier. Obtain legitimately licensed,
   owner-labeled temporal data before attempting temporal risk model training.
2. **Train and verify models.** Provide compatible licensed initial weights and
   training hardware/runtime, train on verified splits, evaluate on withheld
   data, preserve the checkpoint and hash-bound provenance sidecar, then run
   real API inference tests. Until then model inference must stay unavailable.
3. **Implement and test profile, settings, and admin access.** Add secure
   self-service account/profile flows and enforce role checks server-side
   before exposing any admin operations.
4. **Build verified accident-map functionality.** Requires a licensed
   incident dataset with trustworthy coordinates; never infer coordinates
   from the camera registry or fabricate incident markers.
5. **Harden auth and uploads for production.** Consider secure same-origin
   HttpOnly cookie transport, keep bearer credentials out of WebSocket query
   strings, add rate limits and upload resource limits, and enforce private/
   reserved IP blocking after resolving camera hostnames.
6. **Configure authorized external sources** for actual government statistics,
   official weather stations, and institution-approved feeds; test their
   freshness and stale-data behavior.
7. **Complete frontend QA** with keyboard/screen-reader review, mobile and
   desktop viewports, and end-to-end account, upload, camera, filter, map, and
   prediction flows against real configured services.

## Release status

Local development services are available on this machine, and the tested
frontend build/backend API are operational with SQLite. The system is **not
complete for actual accident prediction or production deployment**: there are
no trained model artifacts or usable accident-labeled datasets, significant
account/map product surfaces are missing, optional external data sources are
unconfigured, and production security/accessibility review remains outstanding.
