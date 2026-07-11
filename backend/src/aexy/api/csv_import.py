"""CSV import: authorized upload, preflight, mapping, dry-run, and
rejection-CSV download -- entirely pre-persistence. No endpoint in this
router creates, updates, or deletes a CRM record; that is deliberately a
later, separate phase.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.developers import get_current_developer
from aexy.core.database import get_db
from aexy.models.developer import Developer
from aexy.schemas.csv_import import (
    DEFAULT_CSV_IMPORT_LIMITS,
    CsvColumnMapping,
    CsvImportPreflightResult,
)
from aexy.schemas.csv_import_policy import (
    CsvImportDryRunPolicyResult,
    CsvImportPolicies,
    CsvImportSchemaResponse,
    DuplicateAction,
    InvalidRowPolicy,
)
from aexy.services.crm_service import CRMObjectService
from aexy.services.csv_import_authorization_service import (
    build_authorized_import_targets,
    read_bounded_upload,
    require_import_edit_access,
)
from aexy.services.csv_import_policy_service import CsvImportPolicyService
from aexy.services.csv_import_preflight_service import CsvImportPreflightService
from aexy.services.csv_import_rejection_csv_service import generate_rejection_csv
from aexy.services.data_table_service import TableAccess
from aexy.services.workspace_service import WorkspaceService

csv_import_router = APIRouter(
    prefix="/workspaces/{workspace_id}/crm/objects/{object_id}/imports",
    tags=["CSV Import"],
)


async def _require_object_in_workspace(
    db: AsyncSession, workspace_id: str, object_id: str, user_id: str,
) -> TableAccess:
    """Verify workspace membership, then object-level edit access. Object
    not found or belonging to a different workspace both surface as the
    same 404 `check_access` already raises -- no separate disclosure path."""
    workspace_service = WorkspaceService(db)
    if not await workspace_service.check_permission(workspace_id, user_id, "member"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this workspace")

    obj_service = CRMObjectService(db)
    obj = await obj_service.get_object(object_id)
    if not obj or str(obj.workspace_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object not found")

    return await require_import_edit_access(db, workspace_id, object_id, user_id)


def _parse_mapping_json(mapping_json: str | None) -> list[CsvColumnMapping]:
    if mapping_json is None:
        return []
    try:
        raw = json.loads(mapping_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="mapping_json must be valid JSON")
    if not isinstance(raw, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="mapping_json must be a JSON array")
    return [CsvColumnMapping.model_validate(m) for m in raw]


@csv_import_router.get("/schema", response_model=CsvImportSchemaResponse)
async def get_import_schema(
    workspace_id: str,
    object_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> CsvImportSchemaResponse:
    """Authorized destination attributes for CSV mapping. Hidden, readonly,
    and system-managed attributes are never included."""
    access = await _require_object_in_workspace(db, workspace_id, object_id, str(current_user.id))
    targets = await build_authorized_import_targets(db, object_id, access)
    return CsvImportSchemaResponse(attributes=targets)


@csv_import_router.post("/preflight", response_model=CsvImportPreflightResult)
async def preflight_csv_import(
    workspace_id: str,
    object_id: str,
    file: UploadFile = File(...),
    mapping_json: str | None = Form(default=None),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> CsvImportPreflightResult:
    """Upload a CSV and receive structural + mapping validation. No record
    is created, updated, or deleted; the file is discarded after the
    request and never written to disk."""
    access = await _require_object_in_workspace(db, workspace_id, object_id, str(current_user.id))
    targets = await build_authorized_import_targets(db, object_id, access)
    proposed_mapping = _parse_mapping_json(mapping_json)

    raw_csv = await read_bounded_upload(file, DEFAULT_CSV_IMPORT_LIMITS.max_file_size_bytes)

    service = CsvImportPreflightService()
    return service.preflight(
        raw_csv=raw_csv,
        target_attributes=targets,
        proposed_mapping=proposed_mapping or None,
        filename=file.filename or None,
    )


async def _run_dry_run(
    db: AsyncSession,
    workspace_id: str,
    object_id: str,
    user_id: str,
    file: UploadFile,
    mapping_json: str,
    invalid_row_policy: InvalidRowPolicy,
    unique_match_attribute_id: str,
    duplicate_action: DuplicateAction,
) -> CsvImportDryRunPolicyResult:
    access = await _require_object_in_workspace(db, workspace_id, object_id, user_id)
    targets = await build_authorized_import_targets(db, object_id, access)
    proposed_mapping = _parse_mapping_json(mapping_json)
    if not proposed_mapping:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="mapping_json must include at least one mapping")

    raw_csv = await read_bounded_upload(file, DEFAULT_CSV_IMPORT_LIMITS.max_file_size_bytes)

    policies = CsvImportPolicies(
        invalid_row_policy=invalid_row_policy,
        unique_match_attribute_id=unique_match_attribute_id,
        duplicate_action=duplicate_action,
    )

    service = CsvImportPolicyService(db)
    return await service.dry_run(
        raw_csv=raw_csv,
        target_attributes=targets,
        proposed_mapping=proposed_mapping,
        policies=policies,
        object_id=object_id,
        workspace_id=workspace_id,
        user_id=user_id,
        filename=file.filename or None,
    )


@csv_import_router.post("/dry-run", response_model=CsvImportDryRunPolicyResult)
async def dry_run_csv_import(
    workspace_id: str,
    object_id: str,
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    invalid_row_policy: InvalidRowPolicy = Form(default="all_or_nothing"),
    unique_match_attribute_id: str = Form(...),
    duplicate_action: DuplicateAction = Form(...),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> CsvImportDryRunPolicyResult:
    """Process every logical row through the validated mapping and the
    selected invalid-row / duplicate-matching policies. Never creates,
    updates, or deletes a CRM record -- this is a read-only, deterministic
    preview of what execution would do in a later phase."""
    return await _run_dry_run(
        db, workspace_id, object_id, str(current_user.id),
        file, mapping_json, invalid_row_policy, unique_match_attribute_id, duplicate_action,
    )


@csv_import_router.post("/rejection-csv")
async def download_rejection_csv(
    workspace_id: str,
    object_id: str,
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    invalid_row_policy: InvalidRowPolicy = Form(default="all_or_nothing"),
    unique_match_attribute_id: str = Form(...),
    duplicate_action: DuplicateAction = Form(...),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Recompute the identical dry-run from the same inputs and return a
    downloadable CSV of exactly the rejected (invalid) rows. No dry-run
    state is cached server-side -- the same file, mapping, and policies
    reproduce an equivalent rejection CSV deterministically."""
    result = await _run_dry_run(
        db, workspace_id, object_id, str(current_user.id),
        file, mapping_json, invalid_row_policy, unique_match_attribute_id, duplicate_action,
    )
    csv_bytes = generate_rejection_csv(result)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="rejected_rows.csv"'},
    )
