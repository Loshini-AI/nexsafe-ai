from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import User, UserSession

password_hasher = PasswordHasher()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_token(user_id: str, session_id: str) -> tuple[str, int]:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    expires_at = int(expiry.timestamp())
    access_token = jwt.encode(
        {"sub": user_id, "jti": session_id, "exp": expires_at},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return access_token, expires_at


async def authenticate_token(db: AsyncSession, token: str) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, expired, or revoked token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise unauthorized from exc

    user_id = claims.get("sub")
    session_id = claims.get("jti")
    if not isinstance(user_id, str) or not isinstance(session_id, str):
        raise unauthorized

    active_session = await db.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > int(datetime.now(timezone.utc).timestamp()),
        )
    )
    if active_session is None:
        raise unauthorized

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise unauthorized
    return user


async def current_user(token: str = Depends(oauth2), db: AsyncSession = Depends(get_db)) -> User:
    return await authenticate_token(db, token)
