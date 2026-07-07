from fastapi import FastAPI, status, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import asyncio
import redis
from urllib.parse import quote

from src.dependencies.database import get_db
from src.app_models.models import Link, User
from src.app_models.database import async_engine, Base
from src.cache.redis_client import LinkCache, RateLimiter
from src.config import get_settings
from src.api.auth import get_current_user, router as auth_router
from src.log import get_logger
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
    logger.info("--- Connecting to database ---")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("--- Tables ready ---")
    yield
    await async_engine.dispose()
    logger.info("--- Database shut down ---")


app = FastAPI(
    lifespan=lifespan,
    title="URL Shortener with Analytics",
    description="Shorten links, track clicks, and view analytics per user.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth_router)


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse("static/home.html")


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse("static/index.html")


@app.get("/register", include_in_schema=False)
async def register_page():
    return FileResponse("static/index.html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page():
    return FileResponse("static/index.html")


@app.get("/ui", include_in_schema=False)
async def frontend():
    return FileResponse("static/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg")


@app.get("/api", tags=["meta"])
async def api_info():
    return {
        "message": "URL Shortener API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# health


@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    report = {
        "status": "healthy",
        "services": {"redis": "unhealthy", "database": "unhealthy"},
    }

    try:
        async for session in get_db():
            result = await session.execute(text("SELECT 1"))
            if result:
                report["services"]["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    try:
        r = redis.Redis.from_url(str(settings.REDIS_URL), decode_responses=True)
        if r.ping():
            report["services"]["redis"] = "healthy"
        r.close()
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    if any(v == "unhealthy" for v in report["services"].values()):
        report["status"] = "unhealthy"
        raise HTTPException(status_code=503, detail=report)

    return report


# Links for app


@app.post("/links", response_model=LinkResponse, status_code=201)
async def create_link(
    body: CreateLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many requests")

    expires_at = body.expires_at or (
        datetime.now(timezone.utc) + timedelta(seconds=settings.MAX_TTL_SECONDS)
    )

    link = await create_short_link(
        db=db,
        original_url=body.original_url,
        custom_alias=body.custom_alias,
        expires_at=expires_at,
        max_clicks=body.max_clicks,
        owner_id=current_user.id,
    )
    return link


@app.get("/links/me", response_model=list[LinkResponse])
async def get_my_links(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Link)
        .where(Link.owner_id == current_user.id)
        .order_by(Link.created_at.desc())
    )
    return result.scalars().all()


@app.post("/links/bulk", status_code=201)
async def bulk_links(
    body: BulkCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many requests")

    return await bulk_create(db, body, owner_id=current_user.id)


@app.delete("/links/{code}")
async def delete_link(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Link).where(Link.code == code))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your link")

    link.is_active = False
    await db.commit()
    LinkCache.invalidate(code)

    return {"message": f"Link {code} deactivated"}


# Application analytics


@app.get("/links/{code}/analytics", response_model=AnalyticsResponse)
async def link_analytics(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Link).where(Link.code == code))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your link")

    results = await asyncio.gather(
        clicks_over_time(code),
        clicks_by_country(code),
        clicks_by_device(code),
        clicks_by_browser(code),
        return_exceptions=True,
    )

    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Analytics error for {code}: {r}")
            raise HTTPException(status_code=500, detail="Error fetching analytics")

    time_series, top_countries, device_breakdown, browser_breakdown = results

    return {
        "time_series": time_series,
        "top_countries": top_countries,
        "device_breakdown": device_breakdown,
        "browser_breakdown": browser_breakdown,
    }


@app.get("/{code}")
async def redirect(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host
    if not RateLimiter.is_allowed(ip):
        return RedirectResponse(
            f"/static/link-error.html?message={quote('Too many requests. Please wait a moment and try again.')}&status=429"
        )

    cached_url = LinkCache.get_destination(code)
    if cached_url:
        await record_click(db, code, request)
        return RedirectResponse(url=cached_url, status_code=307)

    result = await db.execute(
        select(Link).where(Link.code == code, Link.is_active.is_(True))
    )
    link = result.scalar_one_or_none()

    if not link:
        return RedirectResponse(
            f"/static/link-error.html?message={quote('This link doesn’t exist or has been deactivated.')}&status=404"
        )

    try:
        destination = await resolve_link(db, code, request)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "This link isn't available."
        return RedirectResponse(
            f"/static/link-error.html?message={quote(detail)}&status={e.status_code}"
        )

    await record_click(db, code, request)
    return RedirectResponse(url=destination, status_code=307)
