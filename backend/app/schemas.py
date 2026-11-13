from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegistrationRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        character_groups = (
            any(character.islower() for character in value),
            any(character.isupper() for character in value),
            any(character.isdigit() for character in value),
            any(not character.isalnum() for character in value),
        )
        if len(value) < 12 or sum(character_groups) < 3:
            raise ValueError(
                "Password must be at least 12 characters and include at least "
                "three of lowercase letters, uppercase letters, numbers, and symbols"
            )
        return value


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=2048)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    weather_station_id: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class CameraOut(BaseModel):
    id: str
    name: str
    latitude: float | None
    longitude: float | None
    weather_station_id: str | None = None
    enabled: bool
    created_at: datetime
    connection_status: str
    model_config = ConfigDict(from_attributes=True)


class EventOut(BaseModel):
    id: str
    camera_id: str | None
    event_type: str
    occurred_at: datetime
    risk_score: float | None
    model_confidence: float | None
    status: str
    assigned_to: str | None
    details: str | None
    model_config = ConfigDict(from_attributes=True)


class EventUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|acknowledged|resolved)$")
    assigned_to: str | None = Field(default=None, max_length=320)
