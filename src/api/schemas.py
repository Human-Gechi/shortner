import re
from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict, EmailStr

# data coming IN from the client


class UserRegisterSchema(BaseModel):
    email: EmailStr
    password: str


class CreateLinkRequest(BaseModel):
    original_url: str = Field(..., description="The long URL to shorten")
    custom_alias: Optional[str] = Field(default=None, min_length=3, max_length=30)
    expires_at: Optional[datetime] = Field(default=None)
    max_clicks: Optional[int] = Field(default=None, ge=1)

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
        if v:
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)

            if v <= datetime.now(timezone.utc):
                raise ValueError("expires_at must be a future datetime")

        return v


class BulkCreateRequest(BaseModel):
    links: List[CreateLinkRequest] = Field(..., min_length=1, max_length=100)


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
    date: datetime
    count: int


class GeoDistribution(BaseModel):
    country: Optional[str] = None
    count: int


class DeviceBreakdown(BaseModel):
    device_type: str
    count: int


class BrowserBreakdown(BaseModel):
    browser: str
    count: int


class AnalyticsResponse(BaseModel):
    time_series: List[TimeSeriesPoint]
    top_countries: List[GeoDistribution]
    device_breakdown: List[DeviceBreakdown]
    browser_breakdown: List[BrowserBreakdown]
