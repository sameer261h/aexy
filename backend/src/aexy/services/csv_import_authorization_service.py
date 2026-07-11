"""Authorization and target-attribute construction shared by every CSV
import endpoint (schema, preflight, dry-run, rejection-csv).

A single seam so hidden/readonly/system-managed filtering happens exactly
once and cannot drift between endpoints -- reuses `TableAuthService`
(object-level access) and `CRMAttributeService` (attribute metadata)
rather than inventing a parallel authorization or attribute-listing path.
"""

from collections.abc import Sequence

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMAttribute
from aexy.schemas.csv_import_policy import CsvFullTargetAttribute
from aexy.services.crm_service import CRMAttributeService
from aexy.services.csv_import_preflight_service import NON_IMPORTABLE_ATTRIBUTE_TYPES
from aexy.services.data_table_service import DataTableService, TableAccess


async def require_import_edit_access(
    db: AsyncSession,
    workspace_id: str,
    object_id: str,
    user_id: str,
) -> TableAccess:
    """Verify object-level edit access. Raises 404/403 exactly like every
    other CRM route's `check_access` call -- no separate error contract
    for CSV import."""
    dts = DataTableService(db)
    return await dts.auth.check_access(object_id, user_id, "edit", workspace_id)


def _is_authorized_for_import(attr: CRMAttribute, access: TableAccess) -> bool:
    """Hidden, readonly, and system-managed attributes are never exposed
    as import targets -- omitted entirely (not merely marked
    non-importable) so mapping to one fails identically to referencing a
    nonexistent attribute. No existence disclosure."""
    if attr.is_system:
        return False
    if attr.slug in access.hidden_columns:
        return False
    if attr.slug in access.readonly_columns:
        return False
    return True


async def build_authorized_import_targets(
    db: AsyncSession,
    object_id: str,
    access: TableAccess,
) -> list[CsvFullTargetAttribute]:
    """Build the target-attribute list actually exposed for CSV mapping."""
    attr_service = CRMAttributeService(db)
    attributes = await attr_service.list_attributes(object_id)
    result: list[CsvFullTargetAttribute] = []
    for attr in attributes:
        if not _is_authorized_for_import(attr, access):
            continue
        importable = attr.attribute_type not in NON_IMPORTABLE_ATTRIBUTE_TYPES
        result.append(
            CsvFullTargetAttribute(
                id=str(attr.id),
                display_name=attr.name,
                slug=attr.slug,
                attribute_type=attr.attribute_type,
                importable=importable,
                is_required=attr.is_required,
                config=attr.config or {},
            )
        )
    return result


async def read_bounded_upload(file: UploadFile, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read an upload in bounded chunks, aborting with 413 as soon as the
    limit is exceeded -- the request body is never read past
    `max_bytes + chunk_size`, so an oversized upload cannot be fully
    buffered into memory before the size is checked."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"CSV upload exceeds the {max_bytes}-byte limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def find_target_by_id(
    targets: Sequence[CsvFullTargetAttribute], target_attribute_id: str
) -> CsvFullTargetAttribute | None:
    for target in targets:
        if target.id == target_attribute_id:
            return target
    return None


__all__ = [
    "require_import_edit_access",
    "build_authorized_import_targets",
    "read_bounded_upload",
    "find_target_by_id",
]
