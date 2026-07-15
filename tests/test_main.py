from fastapi.testclient import TestClient
from backend.app.main import app
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock


client = TestClient(app)


@pytest.mark.asyncio
async def test_api_info():
    res = client.get("/api")
    assert res.json() == {
        "message": "URL Shortener API",
        "version": "1.0.0",
        "docs": "/docs",
    }


async def mock_get_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session.execute.return_value = mock_result
    yield mock_session


@pytest.mark.asyncio
async def test_health_all_healthy():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with (
        patch("backend.app.main.get_db", return_value=mock_get_db()),
        patch("backend.app.main.redis.Redis.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/health")

        assert res.status_code == 200
        assert res.json() == {
            "status": "healthy",
            "services": {"redis": "healthy", "database": "healthy"},
        }


@pytest.mark.asyncio
async def test_health_db_down():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with (
        patch("backend.app.main.get_db", side_effect=Exception("DB connection failed")),
        patch("backend.app.main.redis.Redis.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/health")

        assert res.status_code == 503
        assert res.json()["detail"]["services"]["database"] == "unhealthy"
        assert res.json()["detail"]["services"]["redis"] == "healthy"
        assert res.json()["detail"]["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_redis_down():
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("Redis connection failed")

    with (
        patch("backend.app.main.get_db", return_value=mock_get_db()),
        patch("backend.app.main.redis.Redis.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/health")

        assert res.status_code == 503
        assert res.json()["detail"]["services"]["redis"] == "unhealthy"
        assert res.json()["detail"]["services"]["database"] == "healthy"


@pytest.mark.asyncio
async def test_health_both_down():
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("Redis down")

    with (
        patch("backend.app.main.get_db", side_effect=Exception("DB down")),
        patch("backend.app.main.redis.Redis.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/health")

        assert res.status_code == 503
        assert res.json()["detail"]["status"] == "unhealthy"
        assert res.json()["detail"]["services"]["database"] == "unhealthy"
        assert res.json()["detail"]["services"]["redis"] == "unhealthy"
