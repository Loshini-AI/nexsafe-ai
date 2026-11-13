from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


project_root = Path(__file__).resolve().parents[2]
env_file = project_root / ".env"
if not env_file.is_file():
    env_file = Path(__file__).resolve().parents[1] / ".env"

existing_database = Path("D:/NexSafeAI/data/nexsafe.db")
default_database = (
    existing_database
    if existing_database.is_file()
    else project_root / "data" / "nexsafe.db"
)


class Settings(BaseSettings):
    database_url: str = f"sqlite+aiosqlite:///{default_database.as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 60
    allow_registration: bool = False
    model_weights: str | None = None
    inference_provider: Literal["local", "huggingface"] = "local"
    hf_inference_token: SecretStr | None = None
    hf_object_detection_model: str = Field(
        default="facebook/detr-resnet-50",
        pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$",
    )
    hf_video_max_frames: int = Field(default=8, ge=1, le=16)
    hf_video_max_upload_bytes: int = Field(default=200 * 1024 * 1024, ge=1)
    accident_model_weights: str | None = None
    road_risk_model_weights: str | None = None
    road_risk_positive_classes: str = ""
    dataset_audit_path: str = "D:/NexSafeAI/datasets/uvh26-audit.json"
    dataset_catalog_path: str = str(project_root / "backend" / "datasets" / "catalog.json")
    accident_alert_threshold: float | None = Field(default=None, ge=0, le=1)
    accident_risk_classes: str = "near_miss,accident"
    camera_encryption_key: str = Field(min_length=32)
    camera_allowed_hosts: str = ""
    upload_dir: str = "./data/uploads"
    frontend_origin: str = "http://localhost:3000"
    imd_api_key: SecretStr | None = None
    imd_auth_header: str | None = None
    imd_auth_scheme: str = ""
    imd_station_ids: str = ""
    imd_city_ids: str = ""
    imd_warnings_url: str | None = None
    morth_ogd_resource_id: str | None = None
    ogd_resource_ids: str = ""
    ogd_api_key: SecretStr | None = None
    irad_api_url: str | None = None
    irad_api_token: SecretStr | None = None
    government_data_refresh_seconds: int = Field(default=900, ge=60, le=86400)
    model_config = SettingsConfigDict(env_file=env_file, extra="ignore")

    @model_validator(mode="after")
    def validate_secrets(self):
        if self.jwt_secret == self.camera_encryption_key:
            raise ValueError("JWT_SECRET and CAMERA_ENCRYPTION_KEY must be different")
        return self


def configured_secret(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


settings = Settings()
