from fastapi import FastAPI, status, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import RedirectResponse, JSONResponse
from src.dependencies.database import get_db
from src.app_models.models import Link
from src.cache.redis_client import r, LinkCache, RateLimiter
from sqlalchemy import text, select
import asyncio
from src.app_models.database import async_engine, Base
from contextlib import asynccontextmanager
from src.log import get_logger
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas import LinkResponse, CreateLinkRequest, BulkCreateRequest
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
    except Exception:
        logger.error("Failed to access database")
    try:
        redis_ping = r.ping()
        await r.close()
        if redis_ping:
            health_check["services"]["redis"] = "healthy"
        else:
            health_check["status"] = "unhealthy"
    except Exception:
        logger.error("Redis health check failed")

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
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    link = await create_short_link(
        db=db,
        original_url=link_body.original_url,
        custom_alias=link_body.custom_alias,
        password=link_body.password,
        expires_at=link_body.expires_at,
        max_clicks=link_body.max_clicks,
    )
    return link


@app.get("/code")
async def redirect(
    code: str,
    request: Request,
    backgound_task: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    resolve_code = await resolve_link(db, code, request)
    backgound_task.add_task(record_click, db, code, request)
    return RedirectResponse(url=resolve_code, status_code=301)


@app.get("/links/{code}/analytics")
async def code_analytics(code: str, db: AsyncSession = Depends(get_db)):
    analytics = [
        clicks_by_device(db, code),
        clicks_by_browser(db, code),
        clicks_by_country(db, code),
        clicks_over_time(db, code),
    ]

    result = await asyncio.gather(*analytics)

    return JSONResponse(result)


@app.delete("/links/{code}")
async def delete_link(code: str, db: AsyncSession = Depends(get_db)):
    query = await db.execute(select(Link).where(Link.code == code))
    link = query.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=401, detail="Link Not Found")

    link.is_active = False

    await db.commit()
    LinkCache.invalidate(code)

    return {"Message": f"Link {code} has been deactivated"}


@app.post("/links/bulk")
async def bulks_links(
    bulk_link: BulkCreateRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    bulk = await bulk_create(db, bulk_link)

    return bulk
