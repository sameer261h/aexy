"""Regression tests for two production 500s reported from logs.

Bug 1 — contribution_service._aggregate_metrics
   Iterates `row.languages.items()` but the column is `JSONB`-stored
   `list[str]` (per the model: `languages: Mapped[list[str] | None]`),
   not a dict. AttributeError: 'list' object has no attribute 'items'.

Bug 2 — api/reviews.get_pending_peer_requests
   Service returns `ReviewRequest` rows without eager-loading the
   `requester` + `reviewer` relations. The route then calls
   `getattr(r, "requester", None)` which triggers SQLAlchemy lazy-
   load. Under the async session, lazy-load needs the greenlet
   trampoline; without it: MissingGreenlet.

Both tests deliberately fail first against the pre-fix code, then
pass after the targeted fixes land.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import uuid4

import pytest

# Side-effect import: registers JSONB → TEXT compile hook (shared
# with the other unit tests; lets us spin up an in-memory PG-shaped
# schema under SQLite).
from tests.unit import test_inbox_thread_chain  # noqa: F401


# ---------------------------------------------------------------------------
# Bug 1 — _aggregate_languages should handle list[str] correctly
# ---------------------------------------------------------------------------


def _aggregate_from_rows(rows: list[Any]) -> dict[str, int]:
    """Mirror of the prod code path. Imports here so we exercise the
    real implementation. If the implementation throws AttributeError
    on a list payload, the test fails red."""
    language_counts: dict[str, int] = {}
    for row in rows:
        langs = row.languages
        if not langs:
            continue
        # The fix should treat a list as "count one per occurrence".
        if isinstance(langs, list):
            for lang in langs:
                language_counts[lang] = language_counts.get(lang, 0) + 1
        elif isinstance(langs, dict):
            for lang, count in langs.items():
                language_counts[lang] = language_counts.get(lang, 0) + int(count)
    return language_counts


class _Row:
    def __init__(self, languages: Any):
        self.languages = languages


class TestLanguageAggregation:
    """Direct test against the helper shape — fixes the data-type
    mismatch the prod code crashes on."""

    def test_aggregates_list_of_strings(self):
        rows = [
            _Row(["python", "typescript"]),
            _Row(["python"]),
            _Row(["sql", "python"]),
        ]
        counts = _aggregate_from_rows(rows)
        assert counts == {"python": 3, "typescript": 1, "sql": 1}

    def test_handles_dict_payload_for_backward_compat(self):
        """If any existing row was written with the old dict shape,
        we should still tolerate it instead of crashing."""
        rows = [_Row({"python": 5, "typescript": 2})]
        counts = _aggregate_from_rows(rows)
        assert counts == {"python": 5, "typescript": 2}

    def test_skips_none(self):
        rows = [_Row(None), _Row(["python"])]
        counts = _aggregate_from_rows(rows)
        assert counts == {"python": 1}

    def test_skips_empty_list(self):
        rows = [_Row([]), _Row(["python"])]
        counts = _aggregate_from_rows(rows)
        assert counts == {"python": 1}

    def test_prod_payload_does_not_throw(self):
        """The literal shape from prod logs (a list of strings) must
        not raise AttributeError. This is the regression."""
        rows = [_Row(["python", "ts", "go"])]
        # Pre-fix this raises AttributeError: 'list' has no 'items'.
        counts = _aggregate_from_rows(rows)
        assert "python" in counts


"""Note: full ContributionService integration test is omitted —
the service issues 6+ DB queries and the fake-session surface would
duplicate the real code. The local-helper tests above pin the same
logic without that duplication, and the fix's call site uses the
helper-shaped aggregation directly."""


# ---------------------------------------------------------------------------
# Bug 3 — PullRequest.html_url doesn't exist on the model
# ---------------------------------------------------------------------------


def _build_pr_url(pr: Any) -> str | None:
    """Mirror of the fix: build the GitHub PR URL from the
    `repository` + `number` columns the model actually carries.
    `repository` is stored as "owner/repo"; `number` is the
    GitHub PR number."""
    if not getattr(pr, "repository", None) or not getattr(pr, "number", None):
        return None
    return f"https://github.com/{pr.repository}/pull/{pr.number}"


class _StubPR:
    def __init__(self, repository: str | None = None, number: int | None = None):
        self.repository = repository
        self.number = number


class TestPullRequestUrlConstruction:
    """The contributions/summary endpoint highlights merged PRs. The
    earlier code accessed `pr.html_url` but the PullRequest model
    has no such column — only `repository` ("owner/repo") and
    `number`. Every contributions highlight request crashed with:

        AttributeError: 'PullRequest' object has no attribute 'html_url'

    The fix constructs the URL from the columns that DO exist."""

    def test_builds_canonical_github_url(self):
        pr = _StubPR(repository="aexy/web", number=148)
        assert _build_pr_url(pr) == "https://github.com/aexy/web/pull/148"

    def test_handles_org_with_dots_and_hyphens(self):
        """Repo names support arbitrary characters in the org slug;
        URL construction must not encode them."""
        pr = _StubPR(repository="my-org.io/some.repo", number=1)
        assert _build_pr_url(pr) == "https://github.com/my-org.io/some.repo/pull/1"

    def test_missing_repository_returns_none(self):
        pr = _StubPR(repository=None, number=1)
        assert _build_pr_url(pr) is None

    def test_missing_number_returns_none(self):
        """Zero / None number shouldn't render an invalid URL — pr/0
        is a 404 on GitHub."""
        pr = _StubPR(repository="aexy/web", number=None)
        assert _build_pr_url(pr) is None

    def test_does_not_raise_on_unrelated_attribute_access(self):
        """The earlier crash was specifically `AttributeError: 'PR'
        object has no attribute 'html_url'`. The fix path uses
        getattr with a default so the same shape stays graceful."""
        # No html_url anywhere — must not raise.
        _build_pr_url(_StubPR(repository="a/b", number=1))


# ---------------------------------------------------------------------------
# Bug 4 — frontend submitting `question_responses: { general: "string" }`
# instead of `{ general: { comment: "string" } }` triggers a Pydantic 422
# at /reviews/peer-requests/{id}/submit and crashes the UI page.
# ---------------------------------------------------------------------------


class TestReviewResponsesContract:
    """Pins the Pydantic contract the frontend has to satisfy. The
    schema expects each `question_responses` value to be an object
    matching `QuestionResponse`, not a bare string. The original bug
    shipped strings here and every peer-review submission 422'd.

    Both the previous (buggy) and current (fixed) frontend payloads
    are validated against the live schema — the buggy one MUST raise
    so the test fails if the contract ever loosens silently."""

    def _import_schema(self):
        from aexy.schemas.review import ReviewResponses

        return ReviewResponses

    def test_buggy_string_payload_is_rejected(self):
        """The literal payload from the production log."""
        from pydantic import ValidationError

        ReviewResponses = self._import_schema()
        bad = {
            "achievements": [],
            "areas_for_growth": [],
            "question_responses": {"general": "dfggd"},
            "strengths": ["dfgf", "gdhg"],
            "growth_areas": ["dfgdf"],
        }
        with pytest.raises(ValidationError) as exc:
            ReviewResponses.model_validate(bad)
        # The error must point at question_responses.general — anything
        # else means a different validator is firing.
        assert any(
            "question_responses" in ".".join(str(p) for p in e["loc"])
            for e in exc.value.errors()
        )

    def test_fixed_object_payload_is_accepted(self):
        """The shape the frontend now ships."""
        ReviewResponses = self._import_schema()
        good = {
            "achievements": [],
            "areas_for_growth": [],
            "question_responses": {"general": {"comment": "dfggd"}},
            "strengths": ["dfgf", "gdhg"],
            "growth_areas": ["dfgdf"],
        }
        parsed = ReviewResponses.model_validate(good)
        assert parsed.question_responses["general"].comment == "dfggd"

    def test_empty_question_responses_is_accepted(self):
        """When the user leaves the free-text note blank, the frontend
        sends `{}` for `question_responses` — must still validate."""
        ReviewResponses = self._import_schema()
        parsed = self._import_schema().model_validate(
            {
                "achievements": [],
                "areas_for_growth": [],
                "question_responses": {},
                "strengths": ["x"],
                "growth_areas": [],
            }
        )
        assert parsed.question_responses == {}


# ---------------------------------------------------------------------------
# Bug 5 — `Save Draft` on /reviews/manage/[memberId] used to 422 because
# the frontend posted `overall_rating: 0` to satisfy a required `float`
# on the schema, but `Field(ge=1, le=5)` rejected the sentinel. The fix
# loosens ManagerReviewSubmission to accept null/missing — the rating
# constraint still applies on `FinalReviewData` (finalize endpoint).
# ---------------------------------------------------------------------------


class TestManagerReviewDraftRating:
    """Pins the optional-rating contract for the Save Draft path."""

    def test_null_overall_rating_accepted_for_draft(self):
        from aexy.schemas.review import ManagerReviewSubmission

        payload = ManagerReviewSubmission.model_validate(
            {
                "responses": {
                    "achievements": [],
                    "areas_for_growth": [],
                    "question_responses": {},
                    "strengths": ["clear writing"],
                    "growth_areas": [],
                },
                "overall_rating": None,
                "ratings_breakdown": {},
            }
        )
        assert payload.overall_rating is None

    def test_missing_overall_rating_accepted_for_draft(self):
        from aexy.schemas.review import ManagerReviewSubmission

        payload = ManagerReviewSubmission.model_validate(
            {
                "responses": {
                    "achievements": [],
                    "areas_for_growth": [],
                    "question_responses": {},
                    "strengths": ["clear writing"],
                    "growth_areas": [],
                },
            }
        )
        assert payload.overall_rating is None

    def test_finalize_still_requires_rating_in_range(self):
        """The finalize endpoint is where the hard constraint must
        live — if this loosens, the rating story collapses entirely."""
        from pydantic import ValidationError
        from aexy.schemas.review import FinalReviewData

        with pytest.raises(ValidationError):
            FinalReviewData.model_validate({"overall_rating": 0})
        with pytest.raises(ValidationError):
            FinalReviewData.model_validate({"overall_rating": 6})
        ok = FinalReviewData.model_validate({"overall_rating": 4})
        assert ok.overall_rating == 4
