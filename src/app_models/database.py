from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    url=str(settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True
)

async_session = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass


