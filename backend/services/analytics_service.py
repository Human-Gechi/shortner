from backend.app_models.models import Click, Link
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app_models.database import async_session
from sqlalchemy import select, func
from fastapi.exceptions import HTTPException
from backend.cache.redis_client import UniqueVisitorTracker, ClickCounter
from datetime import datetime, timedelta, timezone
from backend.log import get_logger
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError, OperationalError

logger = get_logger("analytics")


async def clicks_over_time(short_code: str, days: int = 30) -> list[dict] | dict:
    time_threshold = datetime.now(timezone.utc) - timedelta(days=days)

    if days <= 1:
        interval = "hour"
    elif days <= 90:
        interval = "day"
    else:
        interval = "month"

    async with async_session() as session:
        try:
            trunc_field = func.date_trunc(interval, Click.clicked_at)

            query = (
                select(
                    trunc_field.label("time_bucket"),
                    func.count().label("count"),
                )
                .where(Click.link_code == short_code)
                .where(Click.clicked_at >= time_threshold)
                .group_by(trunc_field)
                .order_by(trunc_field)
            )

            result = await session.execute(query)
            rows = result.all()

            return [{"date": row.time_bucket, "count": row.count} for row in rows]

        except OperationalError as e:
            logger.error(f"Database connection timeout: {e}")
            return {"result": None, "error": "Service temporarily unavailable"}

        except ProgrammingError as e:
            logger.error(f"SQL Syntax error in analytics: {e}")
            return {"result": None, "error": "Internal query error"}

        except SQLAlchemyError as e:
            logger.error(f"Generic database error occurred: {e}")
            return {"result": None, "error": "Database error"}

        except Exception as e:
            logger.error(f"Unexpected error in task: {e}")
            return {"result": None, "error": "Unexpected system error"}


async def clicks_by_country(short_code: str) -> list[dict]:
    async with async_session() as session:
        try:
            query = (
                select(Click.country, Click.country_code, func.count().label("count"))
                .where(Click.link_code == short_code)
                .group_by(Click.country, Click.country_code)
                .order_by(func.count().desc())
                .limit(20)
            )
            result = await session.execute(query)
            rows = result.all()
            return [{"country": row.country, "count": row.count} for row in rows]
        except OperationalError as e:
            logger.error(f"Database connection timeout or operational issue: {e}")
            return {"result": None, "error": "Service temporarily unavailable"}

        except ProgrammingError as e:
            logger.error(f"SQL Syntax or Programming error in analytics: {e}")
            return {"result": None, "error": "Internal query error"}

        except SQLAlchemyError as e:
            logger.error(f"Generic database error occurred: {e}")
            return {"result": None, "error": "Database error"}

        except Exception as e:
            logger.error(f"Unexpected error in task: {e}")
            return {"query": None, "error": "Unexpected system error"}


async def clicks_by_device(short_code: str) -> list[dict]:
    async with async_session() as session:
        try:
            query = (
                select(Click.device_type, func.count().label("count"))
                .where(Click.link_code == short_code)
                .group_by(Click.device_type)
                .order_by(func.count().desc())
            )
            result = await session.execute(query)
            rows = result.all()
            return [
                {"device_type": row.device_type, "count": row.count} for row in rows
            ]

        except OperationalError as e:
            logger.error(f"Database connection timeout or operational issue: {e}")
            return {"result": None, "error": "Service temporarily unavailable"}

        except ProgrammingError as e:
            logger.error(f"SQL Syntax or Programming error in analytics: {e}")
            return {"result": None, "error": "Internal query error"}

        except SQLAlchemyError as e:
            logger.error(f"Generic database error occurred: {e}")
            return {"result": None, "error": "Database error"}

        except Exception as e:
            logger.error(f"Unexpected error in task: {e}")
            return {"query": None, "error": "Unexpected system error"}


async def clicks_by_browser(short_code: str) -> list[dict]:
    async with async_session() as session:
        try:
            query = (
                select(Click.browser, func.count().label("count"))
                .where(Click.link_code == short_code)
                .group_by(Click.browser)
                .order_by(func.count().desc())
            )
            result = await session.execute(query)
            rows = result.all()
            return [{"browser": row.browser, "count": row.count} for row in rows]
        except OperationalError as e:
            logger.error(f"Database connection timeout or operational issue: {e}")
            return {"result": None, "error": "Service temporarily unavailable"}

        except ProgrammingError as e:
            logger.error(f"SQL Syntax or Programming error in analytics: {e}")
            return {"result": None, "error": "Internal query error"}

        except SQLAlchemyError as e:
            logger.error(f"Generic database error occurred: {e}")
            return {"result": None, "error": "Database error"}

        except Exception as e:
            logger.error(f"Unexpected error in task: {e}")
            return {"query": None, "error": "Unexpected system error"}


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
