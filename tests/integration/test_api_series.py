"""Integration tests for the Series API routes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestCreateSeries:
    """Test POST /api/v1/series."""

    async def test_create_series(self, client: AsyncClient) -> None:
        payload = {
            "name": f"Test Series {uuid4().hex[:8]}",
            "description": "A test series",
            "target_duration_seconds": 30,
            "default_language": "en-US",
        }
        response = await client.post("/api/v1/series", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["description"] == "A test series"
        assert data["target_duration_seconds"] == 30
        assert data["default_language"] == "en-US"
        assert "id" in data
        assert "created_at" in data

    async def test_create_series_minimal(self, client: AsyncClient) -> None:
        """Only the name field is required."""
        payload = {"name": f"Minimal Series {uuid4().hex[:8]}"}
        response = await client.post("/api/v1/series", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        # Defaults
        assert data["target_duration_seconds"] == 30
        assert data["default_language"] == "en-US"

    async def test_create_series_empty_name_rejected(self, client: AsyncClient) -> None:
        payload = {"name": ""}
        response = await client.post("/api/v1/series", json=payload)
        assert response.status_code == 422

    async def test_create_series_invalid_duration(self, client: AsyncClient) -> None:
        payload = {
            "name": f"Bad Duration {uuid4().hex[:8]}",
            "target_duration_seconds": 45,
        }
        response = await client.post("/api/v1/series", json=payload)
        assert response.status_code == 422


@pytest.mark.integration
class TestListSeries:
    """Test GET /api/v1/series."""

    async def test_list_series(self, client: AsyncClient) -> None:
        # Create two series
        name1 = f"List Series A {uuid4().hex[:8]}"
        name2 = f"List Series B {uuid4().hex[:8]}"
        await client.post("/api/v1/series", json={"name": name1})
        await client.post("/api/v1/series", json={"name": name2})

        response = await client.get("/api/v1/series")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        names = [s["name"] for s in data]
        assert name1 in names
        assert name2 in names

    async def test_list_series_has_episode_count(self, client: AsyncClient) -> None:
        name = f"Count Series {uuid4().hex[:8]}"
        resp = await client.post("/api/v1/series", json={"name": name})
        assert resp.status_code == 201

        response = await client.get("/api/v1/series")
        data = response.json()

        matching = [s for s in data if s["name"] == name]
        assert len(matching) == 1
        assert "episode_count" in matching[0]
        assert matching[0]["episode_count"] == 0


@pytest.mark.integration
class TestGetSeriesNotFound:
    """Test GET /api/v1/series/{id} with non-existent ID."""

    async def test_get_series_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid4())
        response = await client.get(f"/api/v1/series/{fake_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.integration
class TestUpdateSeries:
    """Test PUT /api/v1/series/{id}."""

    async def test_update_series(self, client: AsyncClient) -> None:
        # Create
        name = f"Update Target {uuid4().hex[:8]}"
        create_resp = await client.post("/api/v1/series", json={"name": name})
        assert create_resp.status_code == 201
        series_id = create_resp.json()["id"]

        # Update
        update_payload = {
            "name": f"Updated {uuid4().hex[:8]}",
            "description": "Updated description",
            "target_duration_seconds": 60,
        }
        update_resp = await client.put(f"/api/v1/series/{series_id}", json=update_payload)
        assert update_resp.status_code == 200

        data = update_resp.json()
        assert data["name"] == update_payload["name"]
        assert data["description"] == "Updated description"
        assert data["target_duration_seconds"] == 60

    async def test_update_series_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid4())
        response = await client.put(
            f"/api/v1/series/{fake_id}",
            json={"name": "Nonexistent"},
        )
        assert response.status_code == 404


@pytest.mark.integration
class TestDeleteSeries:
    """Test DELETE /api/v1/series/{id}."""

    async def test_delete_series(self, client: AsyncClient) -> None:
        # Create
        name = f"Delete Target {uuid4().hex[:8]}"
        create_resp = await client.post("/api/v1/series", json={"name": name})
        assert create_resp.status_code == 201
        series_id = create_resp.json()["id"]

        # Delete
        delete_resp = await client.delete(f"/api/v1/series/{series_id}")
        assert delete_resp.status_code == 204

        # Verify gone
        get_resp = await client.get(f"/api/v1/series/{series_id}")
        assert get_resp.status_code == 404

    async def test_delete_series_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid4())
        response = await client.delete(f"/api/v1/series/{fake_id}")
        assert response.status_code == 404
