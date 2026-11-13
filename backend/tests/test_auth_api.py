import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-with-more-than-32-characters")
os.environ.setdefault("CAMERA_ENCRYPTION_KEY", "test-only-camera-key-with-more-than-32-chars")
os.environ.setdefault(
    "FRONTEND_ORIGIN",
    "http://localhost:3000,http://127.0.0.1:3000",
)

import httpx
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import main
from app.db import get_db, initialize_database
from app.models import Base, User
from app.security import hash_password, verify_password


class DatabaseUnavailableSession:
    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, _statement):
        raise ConnectionRefusedError("database unavailable")

    async def scalar(self, _statement):
        raise ConnectionRefusedError("database unavailable")

    async def rollback(self):
        return None


class AuthApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async def override_get_db():
            async with self.session_factory() as session:
                yield session

        main.app.dependency_overrides[get_db] = override_get_db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://test",
        )
        self.previous_allow_registration = main.settings.allow_registration
        main.settings.allow_registration = False

    async def asyncTearDown(self):
        main.settings.allow_registration = self.previous_allow_registration
        main.app.dependency_overrides.clear()
        await self.client.aclose()
        await self.engine.dispose()

    async def test_first_account_registration_and_login(self):
        email = "first.operator@example.invalid"
        password = "test-only-password-123"

        response = await self.client.post(
            "/api/auth/register",
            json={
                "full_name": " First Operator ",
                "email": email,
                "password": password + "A!",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        access_token = response.json()["access_token"]
        self.assertTrue(access_token)
        self.assertEqual(set(response.json()), {"access_token", "token_type"})
        async with self.session_factory() as session:
            user = await session.scalar(select(User).where(User.email == email))
        self.assertIsNotNone(user)
        self.assertEqual(user.full_name, "First Operator")
        self.assertEqual(user.role, "admin")
        self.assertNotEqual(user.password_hash, password + "A!")
        self.assertTrue(user.password_hash.startswith("$argon2id$"))
        self.assertTrue(verify_password(password + "A!", user.password_hash))
        self.assertFalse(verify_password("incorrect-password", user.password_hash))
        self.assertNotIn("password_hash", response.json())
        self.assertNotIn("full_name", response.json())

        status = await self.client.get("/api/auth/registration")
        self.assertEqual(status.json(), {"available": False, "first_account": False})

        login = await self.client.post(
            "/api/auth/token",
            data={"username": email, "password": password + "A!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()["access_token"])
        protected = await self.client.get(
            "/api/system",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        self.assertEqual(protected.status_code, 200)

        auth_headers = {"Authorization": f"Bearer {access_token}"}
        overview = await self.client.get("/api/overview", headers=auth_headers)
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["registered_cameras"], 0)
        self.assertEqual(overview.json()["active_incidents"], 0)
        self.assertEqual(overview.json()["processed_frames"], 0)
        self.assertEqual(overview.json()["inference_status"], "unavailable")
        analytics = await self.client.get("/api/analytics", headers=auth_headers)
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["status"], "insufficient_data")
        self.assertEqual(analytics.json()["event_count"], 0)

    async def test_prediction_api_reports_unavailable_model_without_fake_output(self):
        registration = await self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Test Operator",
                "email": "prediction-test@example.invalid",
                "password": "test-only-password-456A!",
            },
        )
        self.assertEqual(registration.status_code, 201, registration.text)
        token = registration.json()["access_token"]
        access_token = token

        response = await self.client.post(
            "/api/inference/road-risk",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("model unavailable", response.json()["detail"].lower())

        video_response = await self.client.post(
            "/api/inference/accident-detection",
            files={"file": ("unavailable.mp4", b"", "video/mp4")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(video_response.status_code, 503)
        self.assertIn("unavailable", video_response.json()["detail"].lower())

        logout = await self.client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(logout.status_code, 204)
        revoked = await self.client.get(
            "/api/system",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(revoked.status_code, 401)

    async def test_startup_initializer_creates_database_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite+aiosqlite:///{Path(directory) / 'startup.db'}"
            startup_engine = create_async_engine(database_url)
            try:
                with patch("app.db.engine", startup_engine), patch.object(
                    main.settings, "database_url", database_url
                ):
                    await initialize_database()
                async with startup_engine.connect() as connection:
                    tables = await connection.run_sync(
                        lambda sync_connection: inspect(sync_connection).get_table_names()
                    )
                self.assertIn("users", tables)
                self.assertIn("user_sessions", tables)
            finally:
                await startup_engine.dispose()

    async def test_duplicate_and_later_registration_are_rejected(self):
        credentials = {
            "full_name": "Operator",
            "email": "operator@example.invalid",
            "password": "test-only-password-456A!",
        }
        first = await self.client.post("/api/auth/register", json=credentials)
        self.assertEqual(first.status_code, 201, first.text)

        main.settings.allow_registration = True
        duplicate = await self.client.post("/api/auth/register", json=credentials)
        self.assertEqual(duplicate.status_code, 409)

        main.settings.allow_registration = False
        later = await self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Second Operator",
                "email": "second.operator@example.invalid",
                "password": "test-only-password-789A!",
            },
        )
        self.assertEqual(later.status_code, 403)
        self.assertEqual(later.json()["detail"], "Account registration is disabled")

    async def test_registration_rejects_invalid_email_weak_password_and_missing_fields(self):
        base_payload = {
            "full_name": "Test Operator",
            "email": "operator@example.invalid",
            "password": "strong-password-123A!",
        }
        invalid_email = await self.client.post(
            "/api/auth/register",
            json={**base_payload, "email": "not-an-email"},
        )
        self.assertEqual(invalid_email.status_code, 422)

        weak_password = await self.client.post(
            "/api/auth/register",
            json={**base_payload, "password": "alllowercasepassword"},
        )
        self.assertEqual(weak_password.status_code, 422)

        missing_name = await self.client.post(
            "/api/auth/register",
            json={"email": base_payload["email"], "password": base_payload["password"]},
        )
        self.assertEqual(missing_name.status_code, 422)

        missing_fields = await self.client.post("/api/auth/register", json={})
        self.assertEqual(missing_fields.status_code, 422)

    async def test_database_connection_failure_returns_server_error(self):
        async def unavailable_db():
            yield DatabaseUnavailableSession()

        main.app.dependency_overrides[get_db] = unavailable_db
        response = await self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Unavailable User",
                "email": "unavailable@example.invalid",
                "password": "strong-password-123A!",
            },
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Account registration is temporarily unavailable because the database could not be reached",
        )

        status = await self.client.get("/api/auth/registration")
        self.assertEqual(status.status_code, 500)
        self.assertEqual(
            status.json()["detail"],
            "Account registration is temporarily unavailable because the database could not be reached",
        )

    async def test_file_database_persists_account_after_engine_restart(self):
        credentials = {
            "full_name": "Persistent Operator",
            "email": "persistent@example.invalid",
            "password": "Persistent-passphrase-47!",
        }
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nexsafe.db"
            database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
            first_engine = create_async_engine(database_url)
            async with first_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            first_factory = async_sessionmaker(first_engine, expire_on_commit=False)

            async def first_db():
                async with first_factory() as session:
                    yield session

            main.app.dependency_overrides[get_db] = first_db
            registration = await self.client.post("/api/auth/register", json=credentials)
            self.assertEqual(registration.status_code, 201, registration.text)
            await first_engine.dispose()

            restarted_engine = create_async_engine(database_url)
            restarted_factory = async_sessionmaker(restarted_engine, expire_on_commit=False)

            async def restarted_db():
                async with restarted_factory() as session:
                    yield session

            main.app.dependency_overrides[get_db] = restarted_db
            login = await self.client.post(
                "/api/auth/token",
                data={"username": credentials["email"], "password": credentials["password"]},
            )
            self.assertEqual(login.status_code, 200, login.text)
            await restarted_engine.dispose()

    async def test_localhost_and_loopback_origins_are_allowed(self):
        for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
            response = await self.client.options(
                "/api/auth/register",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin)


if __name__ == "__main__":
    unittest.main()
