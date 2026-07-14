"""Bulk import service for GTM cold outreach.

Handles CSV parsing, dedup checking, email verification, CRM record creation,
and optional sequence enrollment.
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMRecord, CRMObject, CRMObjectType

logger = logging.getLogger(__name__)

# Standard CSV column mappings → CRM record value keys
COLUMN_MAP: dict[str, str] = {
    "email": "email",
    "e-mail": "email",
    "email_address": "email",
    "first_name": "first_name",
    "first name": "first_name",
    "firstname": "first_name",
    "last_name": "last_name",
    "last name": "last_name",
    "lastname": "last_name",
    "name": "full_name",
    "full_name": "full_name",
    "company": "company",
    "company_name": "company",
    "organization": "company",
    "title": "title",
    "job_title": "title",
    "job title": "title",
    "position": "title",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "mobile_phone",
    "linkedin": "linkedin_url",
    "linkedin_url": "linkedin_url",
    "website": "website",
    "domain": "domain",
    "city": "city",
    "state": "state",
    "country": "country",
    "industry": "industry",
}


@dataclass
class ImportRow:
    """Parsed row from CSV."""

    row_number: int
    email: str
    values: dict[str, Any]
    status: str = "pending"  # pending, created, duplicate, invalid_email, skipped, error
    record_id: str | None = None
    duplicate_of: str | None = None
    verification_result: str | None = None
    error: str | None = None


@dataclass
class ImportJob:
    """Import job state tracker."""

    job_id: str
    workspace_id: str
    total_rows: int = 0
    processed: int = 0
    created: int = 0
    duplicates: int = 0
    invalid_emails: int = 0
    skipped: int = 0
    errors: int = 0
    status: str = "pending"  # pending, processing, completed, failed
    rows: list[ImportRow] = field(default_factory=list)
    sequence_id: str | None = None
    enrolled: int = 0
    unmapped_headers: list[str] = field(default_factory=list)


class BulkImportService:
    """Service for bulk importing contacts from CSV into CRM + optional sequence enrollment."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # CSV PARSING
    # =========================================================================

    def parse_csv(self, csv_content: str) -> list[dict[str, str]]:
        """Parse CSV content into list of dicts with normalized column names."""
        reader = csv.DictReader(io.StringIO(csv_content))
        rows: list[dict[str, str]] = []

        for raw_row in reader:
            normalized: dict[str, str] = {}
            for col, val in raw_row.items():
                if col is None or val is None:
                    continue
                col_lower = col.strip().lower()
                mapped_key = COLUMN_MAP.get(col_lower, col_lower)
                normalized[mapped_key] = val.strip()
            rows.append(normalized)

        return rows

    # =========================================================================
    # FULL IMPORT PIPELINE
    # =========================================================================

    async def run_import(
        self,
        workspace_id: str,
        csv_content: str,
        verify_emails: bool = True,
        skip_duplicates: bool = True,
        sequence_id: str | None = None,
        object_slug: str = "person",
    ) -> ImportJob:
        """Run the full import pipeline.

        Steps:
        1. Parse CSV
        2. Validate email presence
        3. Check for duplicates (by email)
        4. Optionally verify emails via MillionVerifier
        5. Create CRM records for valid rows
        6. Optionally enroll in outreach sequence

        Returns ImportJob with status of each row.
        """
        job = ImportJob(
            job_id=str(uuid4()),
            workspace_id=workspace_id,
            sequence_id=sequence_id,
        )

        # 1. Parse
        parsed_rows = self.parse_csv(csv_content)
        job.total_rows = len(parsed_rows)

        if not parsed_rows:
            job.status = "completed"
            return job

        # Build ImportRow list
        for idx, row_data in enumerate(parsed_rows, start=1):
            email = row_data.get("email", "").strip().lower()
            job.rows.append(ImportRow(
                row_number=idx,
                email=email,
                values=row_data,
            ))

        # 2. Validate email presence
        for row in job.rows:
            if not row.email or "@" not in row.email:
                row.status = "invalid_email"
                row.error = "Missing or invalid email address"
                job.invalid_emails += 1

        # 3. Dedup check
        if skip_duplicates:
            await self._check_duplicates(workspace_id, job)

        # 4. Email verification (optional)
        if verify_emails:
            await self._verify_emails(workspace_id, job)

        # 5. Create CRM records
        object_id = await self._get_or_create_object(workspace_id, object_slug)
        await self._create_records(workspace_id, object_id, job)

        # 6. Enroll in sequence (optional)
        if sequence_id:
            await self._enroll_in_sequence(workspace_id, sequence_id, job)

        await self.db.commit()

        job.status = "completed"
        job.processed = job.total_rows
        return job

    # =========================================================================
    # DEDUP
    # =========================================================================

    async def _check_duplicates(self, workspace_id: str, job: ImportJob) -> None:
        """Check for existing CRM records with matching emails."""
        pending_rows = [r for r in job.rows if r.status == "pending"]
        if not pending_rows:
            return

        emails = [r.email for r in pending_rows]

        # Build conditions for email match in JSONB values
        email_fields = ("email", "work_email", "personal_email", "contact_email")
        conditions = []
        for field_name in email_fields:
            conditions.append(
                func.lower(CRMRecord.values[field_name].astext).in_(emails)
            )

        existing = (await self.db.execute(
            select(CRMRecord.id, CRMRecord.values)
            .where(
                and_(
                    CRMRecord.workspace_id == workspace_id,
                    CRMRecord.is_archived == False,
                    or_(*conditions),
                )
            )
        )).all()

        # Build email → record_id lookup
        existing_emails: dict[str, str] = {}
        for record_id, values in existing:
            for field_name in email_fields:
                email_val = values.get(field_name, "")
                if email_val:
                    existing_emails[email_val.strip().lower()] = record_id

        # Mark duplicates
        for row in pending_rows:
            if row.email in existing_emails:
                row.status = "duplicate"
                row.duplicate_of = existing_emails[row.email]
                job.duplicates += 1

    # =========================================================================
    # EMAIL VERIFICATION
    # =========================================================================

    async def _verify_emails(self, workspace_id: str, job: ImportJob) -> None:
        """Verify pending emails via configured provider."""
        pending_rows = [r for r in job.rows if r.status == "pending"]
        if not pending_rows:
            return

        try:
            from aexy.integrations.registry import ProviderRegistry

            provider = await ProviderRegistry.get_provider(
                self.db, workspace_id, "email_verification",
            )
            if not provider:
                logger.warning(f"No email verification provider for workspace {workspace_id}, skipping")
                return

            emails = [r.email for r in pending_rows]
            results = await provider.verify_bulk(emails)

            # Map results back to rows
            result_map = {r.email.lower(): r for r in results}
            for row in pending_rows:
                result = result_map.get(row.email)
                if result:
                    row.verification_result = result.result_code
                    if not result.is_valid:
                        row.status = "invalid_email"
                        row.error = f"Email verification failed: {result.result_code}"
                        job.invalid_emails += 1

        except Exception as e:
            logger.warning(f"Email verification error, continuing without: {e}")

    # =========================================================================
    # CRM RECORD CREATION
    # =========================================================================

    async def _get_or_create_object(self, workspace_id: str, slug: str) -> str:
        """Get or create CRM object definition (e.g., 'person')."""
        obj = (await self.db.execute(
            select(CRMObject).where(
                and_(
                    CRMObject.workspace_id == workspace_id,
                    CRMObject.slug == slug,
                )
            )
        )).scalar_one_or_none()

        if obj:
            return obj.id

        # Create the object type
        obj = CRMObject(
            id=str(uuid4()),
            workspace_id=workspace_id,
            name=slug.capitalize(),
            slug=slug,
            plural_name=f"{slug.capitalize()}s",
            object_type=CRMObjectType.PERSON.value if slug == "person" else CRMObjectType.CUSTOM.value,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj.id

    async def _create_records(self, workspace_id: str, object_id: str, job: ImportJob) -> None:
        """Create CRM records for pending rows."""
        pending_rows = [r for r in job.rows if r.status == "pending"]

        for row in pending_rows:
            try:
                # Build display name
                first = row.values.get("first_name", "")
                last = row.values.get("last_name", "")
                full = row.values.get("full_name", "")
                display_name = full or f"{first} {last}".strip() or row.email

                record = CRMRecord(
                    id=str(uuid4()),
                    workspace_id=workspace_id,
                    object_id=object_id,
                    values=row.values,
                    display_name=display_name,
                )
                self.db.add(record)

                row.record_id = record.id
                row.status = "created"
                job.created += 1

            except Exception as e:
                row.status = "error"
                row.error = str(e)[:200]
                job.errors += 1

        await self.db.flush()

    # =========================================================================
    # ATTRIBUTE-AWARE CRM OBJECT IMPORT (used by the CRM object grid's Import
    # CSV action, as opposed to run_import() above which is GTM-specific and
    # writes to a fixed, hardcoded set of contact-shaped keys via COLUMN_MAP).
    #
    # run_import() must stay untouched: GTM's own UI and outreach-sequence
    # enrollment depend on its exact fixed-key contract. Reusing it for
    # arbitrary CRM objects was the bug being fixed here — it writes
    # values under keys like "full_name" while an attribute named "Name"
    # slugifies to "name", so imported data would silently never render in
    # the object's grid (record.values[attr.slug] would find nothing).
    # This method instead resolves the destination object's *real*
    # CRMAttribute slugs and writes values keyed by those, matching exactly
    # what CRMObjectService/CRMAttributeService and the grid already expect.
    # =========================================================================

    async def run_import_into_crm_object(
        self,
        workspace_id: str,
        object_id: str,
        csv_content: str,
        skip_duplicates: bool = True,
    ) -> ImportJob:
        """Import CSV rows into an existing CRM object using its real attribute
        schema. Raises ValueError (caller maps to 4xx) for validation failures
        that should block the whole import before any record is written:
        object not found, empty CSV, or a required attribute with no mapped
        column."""
        from aexy.models.crm import CRMAttribute

        obj = (await self.db.execute(
            select(CRMObject).where(
                and_(CRMObject.id == object_id, CRMObject.workspace_id == workspace_id)
            )
        )).scalar_one_or_none()
        if obj is None:
            raise ValueError("Target CRM object not found in this workspace")

        attrs = (await self.db.execute(
            select(CRMAttribute)
            .where(CRMAttribute.object_id == object_id)
            .order_by(CRMAttribute.position)
        )).scalars().all()
        if not attrs:
            raise ValueError("Target CRM object has no attributes to import into")

        reader = csv.DictReader(io.StringIO(csv_content))
        headers = [h for h in (reader.fieldnames or []) if h]
        if not headers:
            raise ValueError("CSV has no header row")

        def normalize(s: str) -> str:
            return s.strip().lower().replace(" ", "_").replace("-", "_")

        # Map each CSV header to a real attribute slug by matching against
        # the attribute's own slug or name (case/whitespace-insensitive).
        # Unmatched headers are recorded and ignored, never silently merged
        # into a wrong key.
        attrs_by_key = {}
        for a in attrs:
            attrs_by_key[normalize(a.slug)] = a
            attrs_by_key[normalize(a.name)] = a

        header_to_attr: dict[str, CRMAttribute] = {}
        unmapped_headers: list[str] = []
        for h in headers:
            match = attrs_by_key.get(normalize(h))
            if match:
                header_to_attr[h] = match
            else:
                unmapped_headers.append(h)

        mapped_slugs = {a.slug for a in header_to_attr.values()}
        missing_required = [
            a.name for a in attrs
            if a.is_required and a.slug not in mapped_slugs
        ]
        if missing_required:
            raise ValueError(
                "CSV is missing a column for required field(s): "
                + ", ".join(missing_required)
            )

        email_attr = next(
            (a for a in attrs if a.attribute_type == "email" and a.slug in mapped_slugs),
            None,
        )

        job = ImportJob(job_id=str(uuid4()), workspace_id=workspace_id)
        raw_rows = list(reader)
        job.total_rows = len(raw_rows)
        if not raw_rows:
            job.status = "completed"
            return job

        parsed: list[ImportRow] = []
        for idx, raw in enumerate(raw_rows, start=1):
            values: dict[str, Any] = {}
            for h, attr in header_to_attr.items():
                v = (raw.get(h) or "").strip()
                if v:
                    values[attr.slug] = v
            email = values.get(email_attr.slug, "") if email_attr else ""
            row = ImportRow(row_number=idx, email=email, values=values)

            missing_value = [
                a.name for a in attrs
                if a.is_required and not values.get(a.slug)
            ]
            if missing_value:
                row.status = "invalid_email" if email_attr and not email else "error"
                row.error = "Missing required value(s): " + ", ".join(missing_value)
                if row.status == "error":
                    job.errors += 1
                else:
                    job.invalid_emails += 1
            parsed.append(row)
        job.rows = parsed

        if skip_duplicates and email_attr:
            pending = [r for r in job.rows if r.status == "pending" and r.email]
            if pending:
                existing = (await self.db.execute(
                    select(CRMRecord.id, CRMRecord.values)
                    .where(
                        and_(
                            CRMRecord.workspace_id == workspace_id,
                            CRMRecord.object_id == object_id,
                            CRMRecord.is_archived == False,
                        )
                    )
                )).all()
                existing_emails: dict[str, str] = {}
                for record_id, rec_values in existing:
                    v = (rec_values or {}).get(email_attr.slug, "")
                    if v:
                        existing_emails[v.strip().lower()] = record_id
                # Track emails within this CSV batch too — two rows with the
                # same email in one file must not both import as "created".
                seen_in_batch: set[str] = set()
                for row in pending:
                    key = row.email.lower()
                    match = existing_emails.get(key)
                    if match:
                        row.status = "duplicate"
                        row.duplicate_of = match
                        job.duplicates += 1
                    elif key in seen_in_batch:
                        row.status = "duplicate"
                        row.duplicate_of = "duplicate row in this file"
                        job.duplicates += 1
                    else:
                        seen_in_batch.add(key)

        primary_slug = next((a.slug for a in attrs if not a.is_system), attrs[0].slug)
        for row in job.rows:
            if row.status != "pending":
                continue
            try:
                display_name = row.values.get(primary_slug) or row.email or f"Row {row.row_number}"
                record = CRMRecord(
                    id=str(uuid4()),
                    workspace_id=workspace_id,
                    object_id=object_id,
                    values=row.values,
                    display_name=display_name,
                )
                self.db.add(record)
                row.record_id = record.id
                row.status = "created"
                job.created += 1
            except Exception as e:
                row.status = "error"
                row.error = str(e)[:200]
                job.errors += 1

        await self.db.flush()
        await self.db.commit()

        job.status = "completed"
        job.processed = job.total_rows
        job.unmapped_headers = unmapped_headers
        return job

    # =========================================================================
    # SEQUENCE ENROLLMENT
    # =========================================================================

    async def _enroll_in_sequence(
        self, workspace_id: str, sequence_id: str, job: ImportJob,
    ) -> None:
        """Enroll created records in an outreach sequence."""
        from aexy.services.outreach_sequence_service import OutreachSequenceService

        service = OutreachSequenceService(self.db)
        created_rows = [r for r in job.rows if r.status == "created" and r.record_id]

        for row in created_rows:
            try:
                first = row.values.get("first_name", "")
                last = row.values.get("last_name", "")
                full = row.values.get("full_name", "")
                contact_name = full or f"{first} {last}".strip() or None

                await service.enroll_contact(
                    workspace_id=workspace_id,
                    sequence_id=sequence_id,
                    record_id=row.record_id,
                    email=row.email,
                    contact_name=contact_name,
                )
                job.enrolled += 1
            except Exception as e:
                logger.warning(
                    f"Failed to enroll row {row.row_number} in sequence {sequence_id}: {e}"
                )

    # =========================================================================
    # IMPORT SUMMARY
    # =========================================================================

    def get_job_summary(self, job: ImportJob) -> dict[str, Any]:
        """Build a summary dict from an import job."""
        return {
            "job_id": job.job_id,
            "status": job.status,
            "total_rows": job.total_rows,
            "processed": job.processed,
            "created": job.created,
            "duplicates": job.duplicates,
            "invalid_emails": job.invalid_emails,
            "skipped": job.skipped,
            "errors": job.errors,
            "enrolled": job.enrolled,
            "rows": [
                {
                    "row": r.row_number,
                    "email": r.email,
                    "status": r.status,
                    "record_id": r.record_id,
                    "duplicate_of": r.duplicate_of,
                    "error": r.error,
                }
                for r in job.rows
            ],
        }
