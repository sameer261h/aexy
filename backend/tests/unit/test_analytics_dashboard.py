"""
Tests for AnalyticsDashboardService.

These tests verify:
- Skill heatmap generation
- Productivity trends calculation
- Workload distribution analysis
- Collaboration network building
"""

import pytest
from datetime import datetime, timedelta

from aexy.services.analytics_dashboard import AnalyticsDashboardService
from aexy.schemas.analytics import DateRange


class TestAnalyticsDashboardService:
    """Tests for AnalyticsDashboardService."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return AnalyticsDashboardService()

    # Skill Heatmap Tests

    @pytest.mark.asyncio
    async def test_generate_skill_heatmap_with_developers(
        self, service, db_session, sample_developers
    ):
        """Test skill heatmap generation with valid developers."""
        developer_ids = [dev.id for dev in sample_developers]

        result = await service.generate_skill_heatmap(developer_ids, db_session)

        # generate_skill_heatmap now returns a SkillHeatmapData pydantic model.
        assert result is not None
        assert isinstance(result.skills, list)
        assert len(result.developers) == len(sample_developers)

    @pytest.mark.asyncio
    async def test_generate_skill_heatmap_empty_developers(self, service, db_session):
        """Test skill heatmap with no developers."""
        result = await service.generate_skill_heatmap([], db_session)

        assert result is not None
        assert result.skills == []
        assert result.developers == []

    @pytest.mark.asyncio
    async def test_generate_skill_heatmap_aggregates_skills(
        self, service, db_session, sample_developers
    ):
        """Test that skill heatmap aggregates skills from developer fingerprints.

        Skills are derived from each developer's ``skill_fingerprint``. The
        model now exposes ``skills`` as a list of skill-name strings and one
        SkillHeatmapCell per developer/skill pair.
        """
        developer_ids = [dev.id for dev in sample_developers]

        result = await service.generate_skill_heatmap(developer_ids, db_session)

        assert isinstance(result.skills, list)
        assert all(isinstance(name, str) for name in result.skills)
        # Every cell references one of the aggregated skills.
        for cell in result.cells:
            assert cell.skill in result.skills

    @pytest.mark.asyncio
    async def test_generate_skill_heatmap_calculates_coverage(
        self, service, db_session, sample_developers
    ):
        """Test skill proficiency is a bounded percentage."""
        developer_ids = [dev.id for dev in sample_developers]

        result = await service.generate_skill_heatmap(developer_ids, db_session)

        # Proficiency is the per-cell 0-100 score in the current schema.
        for cell in result.cells:
            assert 0 <= cell.proficiency <= 100

    # Productivity Trends Tests
    #
    # get_productivity_trends relies on PostgreSQL's date_trunc() SQL function,
    # which SQLite (used for unit tests) does not provide, so these are skipped
    # here and covered against a real Postgres in integration tests.

    @pytest.mark.skip(reason="get_productivity_trends uses PostgreSQL date_trunc(); unsupported by SQLite test DB")
    @pytest.mark.asyncio
    async def test_get_productivity_trends(
        self, service, db_session, sample_developer, sample_commits_db, sample_pull_requests_db
    ):
        """Test productivity trends calculation."""
        date_range = DateRange(
            start_date=datetime.utcnow() - timedelta(days=30),
            end_date=datetime.utcnow(),
        )

        result = await service.get_productivity_trends(
            [sample_developer.id], date_range, db_session
        )

        assert result is not None
        assert "data_points" in result
        assert "summary" in result

    @pytest.mark.skip(reason="get_productivity_trends uses PostgreSQL date_trunc(); unsupported by SQLite test DB")
    @pytest.mark.asyncio
    async def test_get_productivity_trends_empty_range(
        self, service, db_session, sample_developer
    ):
        """Test productivity trends with no activity in range."""
        # Far future date range
        date_range = DateRange(
            start_date=datetime.utcnow() + timedelta(days=100),
            end_date=datetime.utcnow() + timedelta(days=130),
        )

        result = await service.get_productivity_trends(
            [sample_developer.id], date_range, db_session
        )

        assert result is not None
        assert result["summary"]["total_commits"] == 0

    @pytest.mark.skip(reason="get_productivity_trends uses PostgreSQL date_trunc(); unsupported by SQLite test DB")
    @pytest.mark.asyncio
    async def test_get_productivity_trends_calculates_velocity(
        self, service, db_session, sample_developer, sample_commits_db
    ):
        """Test that velocity metrics are calculated."""
        date_range = DateRange(
            start_date=datetime.utcnow() - timedelta(days=30),
            end_date=datetime.utcnow(),
        )

        result = await service.get_productivity_trends(
            [sample_developer.id], date_range, db_session
        )

        assert "velocity" in result["summary"]

    # Workload Distribution Tests

    @pytest.mark.asyncio
    async def test_get_workload_distribution(
        self, service, db_session, sample_developers, sample_commits_db
    ):
        """Test workload distribution calculation."""
        developer_ids = [sample_developers[0].id]  # Use first developer

        result = await service.get_workload_distribution(developer_ids, db_session)

        # Returns a WorkloadDistribution pydantic model.
        assert result is not None
        assert isinstance(result.items, list)
        assert 0 <= result.imbalance_score <= 1

    @pytest.mark.asyncio
    async def test_get_workload_distribution_empty(self, service, db_session):
        """Test workload distribution with no developers."""
        result = await service.get_workload_distribution([], db_session)

        assert result is not None
        assert result.items == []

    @pytest.mark.asyncio
    async def test_get_workload_distribution_imbalance_score(
        self, service, db_session, sample_developers
    ):
        """Test imbalance score calculation."""
        developer_ids = [dev.id for dev in sample_developers]

        result = await service.get_workload_distribution(developer_ids, db_session)

        assert 0 <= result.imbalance_score <= 1

    # Collaboration Network Tests

    @pytest.mark.asyncio
    async def test_get_collaboration_network(
        self, service, db_session, sample_developer, sample_reviews_db
    ):
        """Test collaboration network generation."""
        result = await service.get_collaboration_network(
            [sample_developer.id], db_session
        )

        # Returns a CollaborationGraph pydantic model.
        assert result is not None
        assert isinstance(result.nodes, list)
        assert isinstance(result.edges, list)

    @pytest.mark.asyncio
    async def test_get_collaboration_network_empty(self, service, db_session):
        """Test collaboration network with no developers."""
        result = await service.get_collaboration_network([], db_session)

        assert result is not None
        assert result.nodes == []
        assert result.edges == []

    @pytest.mark.asyncio
    async def test_get_collaboration_network_nodes_have_properties(
        self, service, db_session, sample_developers
    ):
        """Test that network nodes have required properties."""
        developer_ids = [dev.id for dev in sample_developers]

        result = await service.get_collaboration_network(developer_ids, db_session)

        # Nodes are dicts with id/name/avatar_url/degree keys.
        for node in result.nodes:
            assert "id" in node
            assert "name" in node

    # Activity Heatmap Tests

    @pytest.mark.asyncio
    async def test_generate_activity_heatmap(
        self, service, db_session, sample_developer, sample_commits_db
    ):
        """Test activity heatmap generation."""
        # Signature is (developer_id, db, days=365); returns ActivityHeatmapData.
        result = await service.generate_activity_heatmap(
            sample_developer.id, db_session, days=30
        )

        assert result is not None
        assert isinstance(result.data, list)
        assert result.developer_id == sample_developer.id

    @pytest.mark.asyncio
    async def test_generate_activity_heatmap_invalid_developer(
        self, service, db_session
    ):
        """Test activity heatmap with an unknown developer ID.

        The service does not validate the developer; it produces a full
        day-by-day grid where every day has a zero count.
        """
        result = await service.generate_activity_heatmap(
            "00000000-0000-0000-0000-000000000000", db_session, days=30
        )

        assert result is not None
        assert result.max_count == 0
        assert all(entry["count"] == 0 for entry in result.data)


@pytest.mark.skip(
    reason="AnalyticsDashboardService._calculate_skill_level/_calculate_coverage "
    "were removed; proficiency and skill aggregation are now computed inline "
    "inside generate_skill_heatmap with no separately testable helper methods."
)
class TestSkillHeatmapCalculations:
    """Unit tests for skill heatmap calculation logic."""

    def test_calculate_skill_level_from_frequency(self):
        """Test skill level calculation based on usage frequency."""
        service = AnalyticsDashboardService()

        # High frequency = high level
        high_freq = service._calculate_skill_level(100, 1000)
        low_freq = service._calculate_skill_level(10, 1000)

        assert high_freq > low_freq

    def test_calculate_coverage_percentage(self):
        """Test coverage percentage calculation."""
        service = AnalyticsDashboardService()

        # 3 out of 4 developers have skill
        coverage = service._calculate_coverage(3, 4)
        assert coverage == 75.0

        # All developers have skill
        full_coverage = service._calculate_coverage(4, 4)
        assert full_coverage == 100.0

        # No developers have skill
        no_coverage = service._calculate_coverage(0, 4)
        assert no_coverage == 0.0

    def test_calculate_coverage_zero_division(self):
        """Test coverage calculation handles zero total."""
        service = AnalyticsDashboardService()

        coverage = service._calculate_coverage(0, 0)
        assert coverage == 0.0


@pytest.mark.skip(
    reason="AnalyticsDashboardService._calculate_velocity was removed; velocity "
    "aggregation is now computed inline inside get_productivity_trends."
)
class TestProductivityCalculations:
    """Unit tests for productivity calculation logic."""

    def test_calculate_velocity_from_commits(self):
        """Test velocity calculation from commit data."""
        service = AnalyticsDashboardService()

        commits_per_day = [5, 3, 7, 2, 8, 4, 6]
        velocity = service._calculate_velocity(commits_per_day)

        assert velocity > 0
        assert isinstance(velocity, float)

    def test_calculate_velocity_empty_data(self):
        """Test velocity with no commits."""
        service = AnalyticsDashboardService()

        velocity = service._calculate_velocity([])
        assert velocity == 0.0


@pytest.mark.skip(
    reason="AnalyticsDashboardService._calculate_imbalance was removed; the "
    "imbalance score is now computed inline inside get_workload_distribution."
)
class TestWorkloadCalculations:
    """Unit tests for workload calculation logic."""

    def test_calculate_imbalance_score_balanced(self):
        """Test imbalance score for balanced workload."""
        service = AnalyticsDashboardService()

        # Equal distribution
        workloads = [25, 25, 25, 25]
        score = service._calculate_imbalance(workloads)

        assert score < 0.1  # Nearly balanced

    def test_calculate_imbalance_score_imbalanced(self):
        """Test imbalance score for imbalanced workload."""
        service = AnalyticsDashboardService()

        # Very unequal distribution
        workloads = [90, 5, 3, 2]
        score = service._calculate_imbalance(workloads)

        assert score > 0.5  # Significant imbalance

    def test_calculate_imbalance_empty(self):
        """Test imbalance with no data."""
        service = AnalyticsDashboardService()

        score = service._calculate_imbalance([])
        assert score == 0.0
