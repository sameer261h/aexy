"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthAPI:
    """Tests for health check API endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test main health check endpoint."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "database" in data
        assert "redis" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_check_returns_service_name(self, client: AsyncClient):
        """Test that health check returns correct service name."""
        response = await client.get("/health")

        assert response.json()["service"] == "mailagent"

    @pytest.mark.asyncio
    async def test_health_check_returns_version(self, client: AsyncClient):
        """Test that health check returns version."""
        response = await client.get("/health")

        version = response.json()["version"]
        assert version is not None
        assert len(version) > 0

    @pytest.mark.asyncio
    async def test_readiness_check(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Test Kubernetes readiness probe."""

        async def available() -> bool:
            return True

        monkeypatch.setattr("mailagent.api.health.check_db_connection", available)
        monkeypatch.setattr("mailagent.api.health.check_redis_connection", available)

        response = await client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert "ready" in data

    @pytest.mark.asyncio
    async def test_readiness_check_returns_503_when_dependency_is_down(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Readiness must fail when a required dependency is unavailable."""

        async def unavailable() -> bool:
            return False

        async def available() -> bool:
            return True

        monkeypatch.setattr("mailagent.api.health.check_db_connection", unavailable)
        monkeypatch.setattr("mailagent.api.health.check_redis_connection", available)

        response = await client.get("/ready")

        assert response.status_code == 503
        assert response.json() == {
            "ready": False,
            "database": False,
            "redis": True,
        }

    @pytest.mark.asyncio
    async def test_liveness_check(self, client: AsyncClient):
        """Test Kubernetes liveness probe."""
        response = await client.get("/live")

        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True
