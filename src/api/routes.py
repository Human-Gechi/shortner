from fastapi import FastAPI, status, HTTPException
from src.dependencies.database import get_db
from src.cache.redis_client import r
from sqlalchemy import text
from contextlib import asynccontextmanager
from src.log import get_logger

logger = get_logger("app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" --- Connecting to Database ---")

    yield

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
        "services":{
            "redis": "unhealthy",
            "database": "unhealthy"
        }
    }
    try:
        async for session in get_db():
            result = await session.execute(text("SELECT 1"))
            if result:
                health_check["services"]["database"] = "healthy"
                logger.info(f"Database response verified: {result.scalar()}")
    except Exception as e:
        logger.error(f"Failed to access database")
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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail=health_check
        )
        
    return health_check