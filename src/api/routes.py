from fastapi import FastAPI
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
