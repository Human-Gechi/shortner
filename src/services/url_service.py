import hashlib
import logging
import os
import geoip2.database

from datetime import datetime, timezone
from geoip2.errors import GeoIP2Error
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.cache.redis_client import LinkCache, ClickCounter, UniqueVisitorTracker
from src.api.schemas import BulkCreateRequest
from src.log import get_logger
from src.app_models.models import Link, Click
from src.config import get_settings
from src.utils.helpers import (
    normalize_url,
    verify_password,
    password_hash,
    generate_code,
)
from user_agents import parse
from urllib.parse import urlparse

settings = get_settings()
logger = get_logger("url_service")


async def code_exists(db: AsyncSession, code: str) -> bool:
    result = await db.execute(select(Link).where(Link.code == code))
    return result.scalar_one_or_none() is not None


async def ensure_unique_code(db: AsyncSession, max_retries: int = 5) -> str:
    for _ in range(max_retries):
        candidate = generate_code()
        result = await db.execute(select(Link).where(Link.code == candidate))
        if not result.scalar_one_or_none():
            return candidate
    raise RuntimeError("Failed to generate unique code after 5 retries")


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


async def create_short_link(
    original_url: str,
    db: AsyncSession,
    custom_alias: str | None = None,
    password: str | None = None,
    expires_at: datetime | None = None,
    max_clicks: int | None = None,
):

    clean_url = normalize_url(original_url)
    if not is_valid_url(clean_url):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    if custom_alias:
        if await code_exists(db, custom_alias):
            raise HTTPException(status_code=409, detail="Alias already exists")
        if custom_alias in settings.RESERVED_ALIASES:
            raise HTTPException(status_code=409, detail="Alias is reserved")
        code = custom_alias
    else:
        code = await ensure_unique_code(db)

    hashed_pw = password_hash(password) if password else None

    short_url = f"{settings.DOMAIN}/{code}"

    link = Link(
        code=code,
        short_url=short_url,
        original_url=clean_url,
        password_hash=hashed_pw,
        expires_at=expires_at,
        max_clicks=max_clicks,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    LinkCache.set_destination(
        short_code=code, original_url=clean_url, expires_at=expires_at
    )

    return link


async def resolve_link(db: AsyncSession, short_code: str, request_info: Request):

    destination = LinkCache.get_destination(short_code)

    if not destination:
        result = await db.execute(select(Link).where(Link.code == short_code))
        link = result.scalar_one_or_none()

        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        if not link.is_active:
            raise HTTPException(status_code=410, detail="Link has been deactivated")

        if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
            raise HTTPException(status_code=410, detail="Link has expired")

        if link.max_clicks and link.click_count >= link.max_clicks:
            raise HTTPException(
                status_code=410, detail="Link has reached its click limit"
            )

        if link.password_hash:
            submitted_password = request_info.headers.get("X-Link-Password")
            if not submitted_password:
                raise HTTPException(
                    status_code=401, detail="This link requires a password"
                )
            if not verify_password(link.password_hash, submitted_password):
                raise HTTPException(status_code=401, detail="Wrong password")

        destination = link.original_url

    return destination


async def record_click(db: AsyncSession, short_code: str, request_info: Request):
    try:
        x_forwarded_for = request_info.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            raw_ip = x_forwarded_for.split(",")[0].strip()
        else:
            raw_ip = request_info.client.host if request_info.client else "unknown"

        ua_string = request_info.headers.get("user-agent", "")
        referer = request_info.headers.get("referer") 

        logger.info(f"Recorded click from IP: {raw_ip}, UA: {ua_string}, Referer: {referer}")

    except Exception as e:
        logger.error(f"Failed to record click: {e}")

        if not raw_ip:
            logging.warning(f"Skipping click for {short_code}: No IP provided.")
            return

        ip_hash = hashlib.sha256(f"{raw_ip}{settings.SALT}".encode("utf-8")).hexdigest()

        user_agent = parse(ua_string)
        device_type = (
            "Mobile"
            if user_agent.is_mobile
            else "Tablet"
            if user_agent.is_tablet
            else "Desktop"
        )
        browser_info = (
            f"{user_agent.browser.family} {user_agent.browser.version_string}"
        )
        os_info = f"{user_agent.os.family} {user_agent.os.version_string}"

        country_code = None
        if settings.GEOIP_DB_PATH and os.path.exists(settings.GEOIP_DB_PATH):
            try:
                with geoip2.database.Reader(settings.GEOIP_DB_PATH) as reader:
                    response = reader.city(ip_address=raw_ip)
                    country = response.country.name
                    country_code = response.country.iso_code
                    city = response.city.name if response.city else None
                    region = (
                        response.subdivisions.most_specific.name
                        if response.subdivisions
                        else None
                    )

            except GeoIP2Error:
                country = None
                country_code = None
                city = None
                region = None

            except Exception as e:
                logging.error(f"GeoIP Error: {e}")

        click = Click(
            link_code=short_code,
            ip_hash=ip_hash,
            user_agent=ua_string,
            referer=referer,
            country=country,
            country_code=country_code,
            city=city,
            region=region,
            device=device_type,
            browser=browser_info,
            os=os_info,
        )
        db.add(click)

        result = await db.execute(select(Link).filter(Link.code == short_code))
        link = result.scalars().first()

        if link:
            link.click_count += 1

            is_new_visitor = UniqueVisitorTracker.record(short_code, ip_hash)

            if is_new_visitor:
                link.unique_visitor_count += 1

        await db.commit()
        await db.refresh(click)

        ClickCounter.record_click(short_code)
        
        logger.info(f"Recorded click for {short_code} from {country_code}")

    except Exception as e:
        logger.error(f"Failed to record click for {short_code}: {e}")
        if "db" in locals():
            db.rollback()


async def bulk_create(db: AsyncSession, request: BulkCreateRequest):
    if len(request.links) > settings.MAX_BULK_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Exceeds bulk limit of {settings.MAX_BULK_ITEMS} for links",
        )

    created = []
    failed = []

    for link in request.links:
        try:
            link = await create_short_link(
                db=db,
                original_url=link.original_url,
                custom_alias=link.custom_alias,
                password=link.password,
                expires_at=link.expires_at,
                max_clicks=link.max_clicks,
            )
            created.append(link)
        except HTTPException as e:
            failed.append({"url": link.original_url, "reason": e.detail})
    return {"created": created, "failed": failed}
