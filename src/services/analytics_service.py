from src.app_models.models import Click, Link
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi.exceptions import HTTPException
from src.cache.redis_client import UniqueVisitorTracker, ClickCounter
from datetime import datetime, timedelta, timezone


async def clicks_over_time(
    db: AsyncSession, short_code: str, days: int = 30
) -> list[dict]:
    time_threshold = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(
            func.date_trunc("hour", Click.clicked_at).label("hour"),
            func.count().label("count"),
        )
        .where(Click.link_code == short_code)
        .where(Click.clicked_at >= time_threshold)
        .group_by(func.date_trunc("hour", Click.clicked_at))
        .order_by(func.date_trunc("hour", Click.clicked_at))
    )
    result = await db.execute(query)
    rows = result.all()
    return [{"time": row.hour, "count": row.count} for row in rows]


async def clicks_by_country(db: AsyncSession, short_code: str) -> list[dict]:
    query = (
        select(Click.country, Click.country_code, func.count().label("count"))
        .where(Click.link_code == short_code)
        .group_by(Click.country, Click.country_code)
        .order_by(func.count().desc())
        .limit(20)
    )
    result = await db.execute(query)
    rows = result.all()
    return [
        {"country": row.country, "country_code": row.country_code, "count": row.count}
        for row in rows
    ]


async def clicks_by_device(db: AsyncSession, short_code: str) -> list[dict]:
    query = (
        select(Click.device_type, func.count().label("count"))
        .where(Click.link_code == short_code)
        .group_by(Click.device_type)
        .order_by(func.count().desc())
    )
    result = await db.execute(query)
    rows = result.all()
    return [{"device_type": row.device_type, "count": row.count} for row in rows]


async def clicks_by_browser(db: AsyncSession, short_code: str) -> list[dict]:
    query = (
        select(Click.browser, func.count().label("count"))
        .where(Click.link_code == short_code)
        .group_by(Click.browser)
        .order_by(func.count().desc())
    )
    result = await db.execute(query)
    rows = result.all()
    return [{"browser": row.browser, "count": row.count} for row in rows]


async def get_link_summary(db: AsyncSession, short_code: str) -> dict:
    result = await db.execute(select(Link).where(Link.code == short_code))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Link not found in Database")

    total_clicks = ClickCounter.get_clicks(short_code)
    unique_visitors = UniqueVisitorTracker.count(short_code)

    return {
        "code": link.code,
        "short_url": link.short_url,
        "original_url": link.original_url,
        "title": link.title,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "max_clicks": link.max_clicks,
        "is_active": link.is_active,
        "total_clicks": total_clicks,
        "unique_visitors": unique_visitors,
    }
