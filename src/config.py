from functools import lru_cache
from typing import List, Optional

from pydantic import AnyUrl, Field, SecretStr, field_validator, PostgresDsn
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    # core
    DATABASE_URL: PostgresDsn
    REDIS_URL: AnyUrl
    SECRET_KEY: SecretStr
    DOMAIN: AnyUrl

    # runtime
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str  =  "app.log"

    DEFAULT_CODE_LENGTH: int = Field(default=7, ge=4, le=32)
    CODE_ALPHABET: str = Field(
        default="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_"
    )
    MAX_TTL_SECONDS: int = Field(default=60 * 60 * 24 * 365)  
    RESERVED_ALIASES: List[str] = Field(default_factory=list)
    MAX_BULK_ITEMS: int = Field(default=100)

    BROKER_URL: Optional[AnyUrl] = None
    GEOIP_DB_PATH: Optional[str] = None

    model_config = ConfigDict(env_file=".env", frozen=True)


@lru_cache()
def get_settings() -> Settings:
    return Settings()