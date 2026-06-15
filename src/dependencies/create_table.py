from src.app_models.database import async_engine, Base
import asyncio
from src.log import setup_logging, get_logger

setup_logging()

logger = get_logger("create_table")


async def create_tables():
    async with async_engine.begin() as conn:
        logger.info("--- STARTING TABLE CREATION --- ")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("--- TABLE CREATION COMPLETED --- ")
    await async_engine.dispose()


asyncio.run(create_tables())
