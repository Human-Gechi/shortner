import re
from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, HttpUrl, Field, field_validator, ConfigDict

# data coming IN from the client


class CreateLinkRequest(BaseModel):
    original_url: HttpUrl = Field(..., description="The long URL to shorten")
    custom_alias: Optional[str] = Field(default=None, min_length=3, max_length=30)
    expires_at: Optional[datetime] = Field(default=None)
    title: Optional[str] = Field(default=None, max_length=200)
    max_clicks: Optional[int] = Field(default=None, ge=1)
    password: Optional[str] = Field(default=None, min_length=4, max_length=100)

    @field_validator("custom_alias")
    @classmethod
    def alias_must_be_slug(cls, v):
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9\-_]{3,30}$", v):
            raise ValueError(
                "Alias can only contain letters, numbers, hyphens, underscores"
            )
        RESERVED = {"api", "admin", "docs", "metrics", "health", "static"}
        if v.lower() in RESERVED:
            raise ValueError(f"'{v}' is a reserved keyword. Use a different alias")
        return v

    @field_validator("expires_at")
    @classmethod
    def expiry_must_be_future(cls, v):
        if v and v <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be a future datetime")
        return v


class BulkCreateRequest(BaseModel):
    links: List[CreateLinkRequest] = Field(..., min_length=1, max_length=100)


class AccessPasswordRequest(BaseModel):
    code: str
    password: str = Field(..., min_length=1)


# data going OUT to the client


class LinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    short_url: str
    original_url: str
    click_count: int = 0
    created_at: datetime
    expires_at: Optional[datetime]
    is_active: bool


class TimeSeriesPoint(BaseModel):
    date: str
    clicks: int


class GeoDistribution(BaseModel):
    country: str
    clicks: int
    percentage: float


class DeviceBreakdown(BaseModel):
    device_type: str
    clicks: int
    percentage: float


class AnalyticsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    link: LinkResponse
    total_clicks: int
    unique_visitors: int
    clicks_last_7_days: int
    clicks_last_30_days: int
    time_series: List[TimeSeriesPoint]
    top_countries: List[GeoDistribution]
    device_breakdown: List[DeviceBreakdown]
    top_referers: List[dict]


class PaginatedLinksResponse(BaseModel):
    items: List[LinkResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# internal models used inside the app, never returned directly to clients


class CacheEntry(BaseModel):
    original_url: str
    is_active: bool
    expires_at: Optional[str]
    click_count: int
    max_clicks: Optional[int]
    password_hash: Optional[str]


class GeoIPResult(BaseModel):
    ip: str
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    is_success: bool = False
