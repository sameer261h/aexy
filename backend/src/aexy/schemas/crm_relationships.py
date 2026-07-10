"""Read-only schemas for CRM record relationship navigation.

Covers resolving `record_reference` attribute values into authorized
summaries, deriving incoming backlinks, and searching candidate records for
a future picker. No mutation/write schemas live here -- see
`DEEPSEEK_RELATIONSHIP_VALUES_HANDOFF`-owned normalization utility (a
separate worktree) for write-side value handling.
"""

from pydantic import BaseModel


class RelatedRecordSummary(BaseModel):
    """One resolved reference: either a fully-authorized summary, or an
    opaque placeholder when the target is stale, foreign-workspace, or
    otherwise inaccessible. When `accessible` is False, every other field
    except `record_id` stays None -- the caller already held the ID (it was
    stored on their own record), so echoing it back discloses nothing new;
    but no label or object identity is ever fetched or returned for it.
    """

    attribute_id: str
    record_id: str
    accessible: bool
    object_id: str | None = None
    object_label: str | None = None
    record_label: str | None = None
    is_archived: bool | None = None


class RelationshipGroup(BaseModel):
    """One `record_reference` attribute on the viewed record's object,
    with its stored value(s) resolved to summaries in stored order."""

    attribute_id: str
    attribute_name: str
    target_object_id: str
    allow_multiple: bool
    total: int
    items: list[RelatedRecordSummary]


class RelationshipsResponse(BaseModel):
    groups: list[RelationshipGroup]


class BacklinkItem(RelatedRecordSummary):
    """A backlink is always accessible (inaccessible sources are excluded
    entirely rather than shown as placeholders -- unlike outgoing
    references, the viewer never held these IDs, so there is nothing to
    echo back)."""

    source_object_id: str
    source_object_label: str


class BacklinksResponse(BaseModel):
    items: list[BacklinkItem]
    total: int
    limit: int
    offset: int


class CandidateRecord(BaseModel):
    record_id: str
    record_label: str
    is_archived: bool


class CandidateSearchResponse(BaseModel):
    items: list[CandidateRecord]
    total: int
    limit: int
    offset: int
