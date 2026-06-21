from fastapi import FastAPI, status, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from src.dependencies.database import get_db
from src.app_models.models import Link
from src.cache.redis_client import LinkCache, RateLimiter
from sqlalchemy import text, select
from datetime import datetime, timedelta, timezone
import asyncio
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.config import get_settings
import redis
from src.app_models.database import async_engine, Base
from contextlib import asynccontextmanager
from src.log import get_logger
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas import (
    LinkResponse,
    CreateLinkRequest,
    BulkCreateRequest,
    AnalyticsResponse,
)
from src.services.url_service import (
    create_short_link,
    resolve_link,
    record_click,
    bulk_create,
)
from src.services.analytics_service import (
    clicks_over_time,
    clicks_by_browser,
    clicks_by_country,
    clicks_by_device,
)

logger = get_logger("app")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" --- Connecting to Database ---")
    async with async_engine.begin() as conn:
        logger.info("--- STARTING TABLE CREATION --- ")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("--- TABLE CREATION COMPLETED --- ")
    yield

    await async_engine.dispose()

    logger.info("--- Database Shutdown ---")


app = FastAPI(
    lifespan=lifespan,
    title="Url Shortner with Analytics",
    description="Processes and tracks user link shortner clicks",
    version="1.0.0",
    summary="Link Shortner",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/ui")
async def frontend():
    return FileResponse("static/index.html")

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Link Shortener & Analytics API",
        "version": "1.0.0",
        "status": "operational",
        "documentation": "/docs",
        "repository": "https://github.com/Human-Gechi/shortner",
    }


@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    health_check = {
        "status": "healthy",
        "services": {"redis": "unhealthy", "database": "unhealthy"},
    }

    try:
        async for session in get_db():
            result = await session.execute(text("SELECT 1"))
            if result:
                health_check["services"]["database"] = "healthy"
                logger.info(f"Database response verified: {result.scalar()}")
    except Exception as e:
        logger.error(f"Failed to access database: {e}")

    try:
        temp_r = redis.Redis.from_url(str(settings.REDIS_URL), decode_responses=True)

        if temp_r.ping():
            health_check["services"]["redis"] = "healthy"

        temp_r.close()
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    if (
        health_check["services"]["database"] == "unhealthy"
        or health_check["services"]["redis"] == "unhealthy"
    ):
        health_check["status"] = "unhealthy"

    if health_check["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health_check
        )

    return health_check


@app.post("/links", response_model=LinkResponse)
async def create_link(
    link_body: CreateLinkRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    if link_body.expires_at is None:
        final_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=settings.MAX_TTL_SECONDS
        )
    else:
        final_expiry = link_body.expires_at

    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    link = await create_short_link(
        db=db,
        original_url=link_body.original_url,
        custom_alias=link_body.custom_alias,
        password=link_body.password,
        expires_at=final_expiry,
        max_clicks=link_body.max_clicks,
    )
    return link


@app.get("/{code}")
async def redirect(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")

    cached_url = LinkCache.get_destination(code)

    query = await db.execute(select(Link).where(Link.code == code, Link.is_active))
    link = query.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Link not found or deactivated")

    if cached_url:
        resolve_code = await resolve_link(db, code, request)
        await record_click(db, code, request)
        return RedirectResponse(url=resolve_code, status_code=307)


@app.get("/links/{code}/analytics", response_model=AnalyticsResponse)
async def code_analytics(code: str):
    analytics = [
        clicks_over_time(code),
        clicks_by_country(code),
        clicks_by_device(code),
        clicks_by_browser(code),
    ]

    result = await asyncio.gather(*analytics, return_exceptions=True)

    for res in result:
        if isinstance(res, Exception):
            raise HTTPException(
                status_code=500, detail="Error compiling analytics for link"
            )

    time_series, top_countries, device_breakdown, browser_breakdown = result

    return {
        "time_series": time_series,
        "top_countries": top_countries,
        "device_breakdown": device_breakdown,
        "browser_breakdown": browser_breakdown,
    }


@app.delete("/links/{code}")
async def delete_link(code: str, db: AsyncSession = Depends(get_db)):
    query = await db.execute(select(Link).where(Link.code == code))
    link = query.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=401, detail="Link Not Found")

    if link.expires_at > datetime.now(timezone.utc):
        link.is_active = False

    await db.commit()
    LinkCache.invalidate(code)

    return {"Message": f"Link with short code: {code} has been deactivated"}


@app.post("/links/bulk")
async def bulks_links(
    bulk_link: BulkCreateRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    bulk = await bulk_create(db, bulk_link)

    return bulk
