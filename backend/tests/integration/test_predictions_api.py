"""
Integration tests for Predictions API endpoints.

These tests verify:
- Attrition risk prediction
- Burnout risk assessment
- Performance trajectory prediction
- Team health analysis

Notes on drift from the original (SQLite / older-code) version of this file:
- Prediction routes are mounted under ``/api/v1/predictions`` (not
  ``/api/predictions``) and all require authentication. A caller may always
  read predictions about themselves; reading about other developers requires
  an admin role in a shared workspace (``_require_target_developer_visibility``).
- The attrition/burnout/trajectory/team-health computations now call a real
  LLM via ``get_llm_gateway``. Those happy-path tests are skipped in the
  integration tier because they would make live, slow, non-deterministic LLM
  calls (see skip reasons). The auth/validation/not-found/cache paths that do
  NOT hit the LLM are still exercised.
- The trajectory endpoint takes ``months`` (3-12), not ``months_ahead``.
- Endpoints removed since these tests were written: ``/skill-gaps``,
  ``/attrition/batch``, and ``/cached/{developer_id}`` (cache is now read via
  ``GET /insights/{developer_id}`` and cleared via ``DELETE /insights/{id}``).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.config import get_settings
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace, WorkspaceMember

settings = get_settings()

API = "/api/v1/predictions"

# Valid UUID that is guaranteed absent from the DB. Used instead of the old
# "nonexistent-id" sentinel so routes exercise the not-found path rather than
# 500-ing on a malformed UUID param.
ABSENT_UUID = "00000000-0000-0000-0000-000000000000"


def _token(developer_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    payload = {"sub": developer_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _auth(developer_id: str) -> dict:
    return {"Authorization": f"Bearer {_token(developer_id)}"}


@pytest_asyncio.fixture
async def workspace_devs(db_session: AsyncSession):
    """Create a workspace with an admin caller and several active members.

    Returns (caller, [developers]). The caller is an admin in the same active
    workspace as every developer, so visibility checks pass.
    """
    devs = [
        Developer(id=str(uuid4()), name=f"Dev {i}", email=f"pred-{uuid4().hex[:6]}@test.com")
        for i in range(4)
    ]
    db_session.add_all(devs)
    await db_session.flush()

    ws = Workspace(
        id=str(uuid4()),
        name="Predictions WS",
        slug=f"pred-ws-{uuid4().hex[:6]}",
        owner_id=devs[0].id,
    )
    db_session.add(ws)
    await db_session.flush()

    for d in devs:
        db_session.add(
            WorkspaceMember(
                workspace_id=ws.id,
                developer_id=d.id,
                role="admin",
                status="active",
            )
        )
    await db_session.commit()
    for d in devs:
        await db_session.refresh(d)

    return devs[0], devs


class TestPredictionsAPI:
    """Integration tests for /predictions endpoints."""

    # Attrition Risk Tests

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_attrition_risk(self, client: AsyncClient, workspace_devs):
        """Test GET /predictions/attrition/{developer_id} endpoint."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/attrition/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        assert "risk_score" in data
        assert "risk_level" in data
        assert 0 <= data["risk_score"] <= 1
        assert data["risk_level"] in ["low", "moderate", "high", "critical"]

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_attrition_risk_with_force_refresh(
        self, client: AsyncClient, workspace_devs
    ):
        """Test attrition risk with cache bypass."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/attrition/{caller.id}",
            headers=_auth(caller.id),
            params={"use_cache": False},
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_attrition_risk_not_found(
        self, client: AsyncClient, workspace_devs
    ):
        """Test attrition risk for a non-existent developer.

        A valid-but-absent developer id has no active workspace membership, so
        the visibility check returns 404 before any LLM work.
        """
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/attrition/{ABSENT_UUID}", headers=_auth(caller.id)
        )

        assert response.status_code in [404, 403]

    # Burnout Risk Tests

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_burnout_risk(self, client: AsyncClient, workspace_devs):
        """Test GET /predictions/burnout/{developer_id} endpoint."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/burnout/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        assert "risk_score" in data
        assert "risk_level" in data
        assert "indicators" in data

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_burnout_risk_includes_work_patterns(
        self, client: AsyncClient, workspace_devs
    ):
        """Test that burnout risk includes work pattern analysis."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/burnout/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        if data.get("work_pattern_analysis"):
            assert "weekend_commits_percent" in data["work_pattern_analysis"]

    # Performance Trajectory Tests

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_performance_trajectory(
        self, client: AsyncClient, workspace_devs
    ):
        """Test GET /predictions/trajectory/{developer_id} endpoint."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/trajectory/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        assert "trajectory" in data
        assert data["trajectory"] in [
            "accelerating", "steady", "plateauing", "declining"
        ]

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_performance_trajectory_with_months(
        self, client: AsyncClient, workspace_devs
    ):
        """Test trajectory with custom prediction window."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/trajectory/{caller.id}",
            headers=_auth(caller.id),
            params={"months": 12},
        )

        assert response.status_code == 200

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_trajectory_includes_career_readiness(
        self, client: AsyncClient, workspace_devs
    ):
        """Test that trajectory includes career readiness."""
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/trajectory/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        if "career_readiness" in data:
            assert "next_level" in data["career_readiness"]

    # Team Health Tests

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_team_health(self, client: AsyncClient, workspace_devs):
        """Test POST /predictions/team-health endpoint."""
        caller, devs = workspace_devs
        developer_ids = [str(dev.id) for dev in devs]

        response = await client.post(
            f"{API}/team-health",
            headers=_auth(caller.id),
            json={"developer_ids": developer_ids},
        )

        assert response.status_code == 200
        data = response.json()
        assert "health_score" in data
        assert "health_grade" in data
        assert 0 <= data["health_score"] <= 1
        assert data["health_grade"] in ["A", "B", "C", "D", "F"]

    @pytest.mark.skip(
        reason="Happy path calls a live LLM (get_llm_gateway) -> slow, costly, "
        "non-deterministic. Not suitable for the integration tier."
    )
    @pytest.mark.asyncio
    async def test_get_team_health_includes_risks(
        self, client: AsyncClient, workspace_devs
    ):
        """Test that team health includes risk analysis."""
        caller, devs = workspace_devs
        developer_ids = [str(dev.id) for dev in devs]

        response = await client.post(
            f"{API}/team-health",
            headers=_auth(caller.id),
            json={"developer_ids": developer_ids},
        )

        assert response.status_code == 200
        data = response.json()
        assert "risks" in data
        assert "strengths" in data

    @pytest.mark.asyncio
    async def test_get_team_health_empty_team(
        self, client: AsyncClient, workspace_devs
    ):
        """Test team health with no developers.

        Empty developer_ids is rejected with 400 before any LLM work.
        """
        caller, _ = workspace_devs
        response = await client.post(
            f"{API}/team-health",
            headers=_auth(caller.id),
            json={"developer_ids": []},
        )

        assert response.status_code in [200, 400]

    # Skill Gaps Prediction Tests

    @pytest.mark.skip(
        reason="Endpoint removed: POST /predictions/skill-gaps no longer exists "
        "in the predictions router."
    )
    @pytest.mark.asyncio
    async def test_predict_skill_gaps(self, client: AsyncClient, workspace_devs):
        """Test POST /predictions/skill-gaps endpoint."""
        caller, devs = workspace_devs
        developer_ids = [str(dev.id) for dev in devs]

        response = await client.post(
            f"{API}/skill-gaps",
            headers=_auth(caller.id),
            json={
                "developer_ids": developer_ids,
                "roadmap_skills": ["Kubernetes", "Rust", "Machine Learning"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "gaps" in data or "skill_gaps" in data

    @pytest.mark.skip(
        reason="Endpoint removed: POST /predictions/skill-gaps no longer exists "
        "in the predictions router."
    )
    @pytest.mark.asyncio
    async def test_predict_skill_gaps_with_timeline(
        self, client: AsyncClient, workspace_devs
    ):
        """Test skill gaps prediction with timeline."""
        caller, devs = workspace_devs
        developer_ids = [str(dev.id) for dev in devs]

        response = await client.post(
            f"{API}/skill-gaps",
            headers=_auth(caller.id),
            json={
                "developer_ids": developer_ids,
                "roadmap_skills": ["GraphQL", "WebAssembly"],
                "timeline_months": 6,
            },
        )

        assert response.status_code == 200

    # Batch Predictions Tests

    @pytest.mark.skip(
        reason="Endpoint removed: POST /predictions/attrition/batch no longer "
        "exists in the predictions router."
    )
    @pytest.mark.asyncio
    async def test_batch_attrition_analysis(
        self, client: AsyncClient, workspace_devs
    ):
        """Test POST /predictions/attrition/batch endpoint."""
        caller, devs = workspace_devs
        developer_ids = [str(dev.id) for dev in devs]

        response = await client.post(
            f"{API}/attrition/batch",
            headers=_auth(caller.id),
            json={"developer_ids": developer_ids},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or "results" in data

    # Cache Management Tests

    @pytest.mark.asyncio
    async def test_get_cached_insights(self, client: AsyncClient, workspace_devs):
        """Test GET /predictions/insights/{developer_id} endpoint.

        Cache read does not hit the LLM; with no cached insights it returns an
        empty list.
        """
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/insights/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_clear_cached_insights(self, client: AsyncClient, workspace_devs):
        """Test DELETE /predictions/insights/{developer_id} endpoint."""
        caller, _ = workspace_devs
        response = await client.delete(
            f"{API}/insights/{caller.id}", headers=_auth(caller.id)
        )

        assert response.status_code in [200, 204]


class TestPredictionsAPIValidation:
    """Tests for predictions API input validation."""

    @pytest.mark.asyncio
    async def test_team_health_missing_developer_ids(
        self, client: AsyncClient, workspace_devs
    ):
        """Test team health without developer_ids."""
        caller, _ = workspace_devs
        response = await client.post(
            f"{API}/team-health",
            headers=_auth(caller.id),
            json={},
        )

        assert response.status_code == 422

    @pytest.mark.skip(
        reason="Endpoint removed: POST /predictions/skill-gaps no longer exists "
        "in the predictions router."
    )
    @pytest.mark.asyncio
    async def test_skill_gaps_missing_skills(
        self, client: AsyncClient, workspace_devs
    ):
        """Test skill gaps without roadmap_skills."""
        caller, devs = workspace_devs
        response = await client.post(
            f"{API}/skill-gaps",
            headers=_auth(caller.id),
            json={"developer_ids": [str(devs[0].id)]},
        )

        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_trajectory_invalid_months(
        self, client: AsyncClient, workspace_devs
    ):
        """Test trajectory with invalid months.

        The endpoint validates ``months`` with ge=3/le=12, so a negative value
        is rejected with 422 before any LLM work.
        """
        caller, _ = workspace_devs
        response = await client.get(
            f"{API}/trajectory/{caller.id}",
            headers=_auth(caller.id),
            params={"months": -5},
        )

        assert response.status_code in [400, 422]
