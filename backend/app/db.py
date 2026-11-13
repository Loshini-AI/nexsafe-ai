from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


async def get_db():
    async with SessionLocal() as session:
        yield session


async def initialize_database() -> None:
    database_path = make_url(settings.database_url).database
    if engine.dialect.name == "sqlite" and database_path and database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
