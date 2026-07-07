import hashlib
import httpx

from datetime import datetime, timezone
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
    expires_at: datetime | None = None,
    max_clicks: int | None = None,
    owner_id: int | None = None,
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

    short_url = f"{settings.DOMAIN}/{code}"

    link = Link(
        code=code,
        short_url=short_url,
        original_url=clean_url,
        expires_at=expires_at,
        max_clicks=max_clicks,
        owner_id=owner_id,
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

        destination = link.original_url

    return destination


async def geolocate_ip(ip: str) -> dict:
    fallback = {"country": None, "country_code": None, "city": None, "region": None}

    if not ip or ip in ("127.0.0.1", "::1", "unknown"):
        return fallback

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,countryCode,regionName,city"},
            )
            data = resp.json()
    except Exception as e:
        logger.warning(f"Geolocation lookup failed for {ip}: {e}")
        return fallback

    if data.get("status") != "success":
        logger.warning(f"Geolocation lookup returned no result for {ip}: {data}")
        return fallback

    return {
        "country": data.get("country"),
        "country_code": data.get("countryCode"),
        "city": data.get("city"),
        "region": data.get("regionName"),
    }


async def record_click(
    db: AsyncSession,
    short_code: str,
    request_info: Request,
):
    try:
        x_forwarded_for = request_info.headers.get("X-Forwarded-For")

        if x_forwarded_for:
            raw_ip = x_forwarded_for.split(",")[0].strip()
        else:
            raw_ip = request_info.client.host if request_info.client else "unknown"

        if not raw_ip:
            logger.warning(f"Skipping click recording for {short_code}: No IP found.")
            return

        ua_string = request_info.headers.get("user-agent", "")
        referer = request_info.headers.get("referer")

        logger.info(f"Recording click | Code={short_code} | IP={raw_ip}")

        ip_hash = hashlib.sha256(f"{raw_ip}{settings.SALT}".encode("utf-8")).hexdigest()

        user_agent = parse(ua_string)

        if user_agent.is_mobile:
            device_type = "Mobile"
        elif user_agent.is_tablet:
            device_type = "Tablet"
        else:
            device_type = "Desktop"

        browser_info = (
            f"{user_agent.browser.family} {user_agent.browser.version_string}"
        )

        os_info = f"{user_agent.os.family} {user_agent.os.version_string}"

        geo = await geolocate_ip(raw_ip)
        country = geo["country"]
        country_code = geo["country_code"]
        city = geo["city"]
        region = geo["region"]

        click = Click(
            link_code=short_code,
            ip_hash=ip_hash,
            user_agent=ua_string,
            referer=referer,
            country=country,
            country_code=country_code,
            city=city,
            region=region,
            device_type=device_type,
            browser=browser_info,
            os=os_info,
        )

        db.add(click)

        result = await db.execute(select(Link).where(Link.code == short_code))

        link = result.scalar_one_or_none()

        if link:
            link.click_count += 1

            is_new_visitor = UniqueVisitorTracker.record(
                short_code,
                ip_hash,
            )

            if is_new_visitor:
                link.unique_visitor_count += 1

            limit_just_reached = link.max_clicks and link.click_count >= link.max_clicks
        else:
            limit_just_reached = False

        await db.commit()
        await db.refresh(click)

        ClickCounter.record_click(short_code)

        if limit_just_reached:
            LinkCache.invalidate(short_code)

        logger.info(f"Successfully recorded click for {short_code}")

    except Exception as e:
        logger.exception(f"Failed to record click for {short_code}: {e}")

        try:
            await db.rollback()
        except Exception:
            pass


async def bulk_create(
    db: AsyncSession, request: BulkCreateRequest, owner_id: int | None = None
):
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
                expires_at=link.expires_at,
                max_clicks=link.max_clicks,
                owner_id=owner_id,
            )
            created.append(link)
        except HTTPException as e:
            failed.append({"url": link.original_url, "reason": e.detail})
    return {"created": created, "failed": failed}