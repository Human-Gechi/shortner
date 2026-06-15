from src.dependencies.database import get_db
import asyncio
from sqlalchemy import text


async def test_my_generator():
    try:
        print("Starting database connectivity check...")
        async for session in get_db():
            result = await session.execute(text("SELECT 1"))
            print(f"Database response verified: {result.scalar()}")
    except Exception as e:
        print(f"Failed to access database stream: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_my_generator())
