"""Reporting/analytics background activities.

Activities:
    - process_export_job: Gather data for an export job and render the file.
    - deliver_scheduled_reports: Poll due scheduled reports, render + deliver them.
    - cleanup_expired_exports: Delete export jobs (and files) past their expiry.

These wire the reporting feature's async layer, which was previously missing —
export jobs were created but never processed (stuck "pending" forever), and
scheduled reports were saved but never delivered.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import activity

from aexy.core.database import async_session_maker

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT DATACLASSES
# =============================================================================

@dataclass
class ProcessExportInput:
    """Input for processing a single export job."""

    job_id: str


@dataclass
class DeliverScheduledReportsInput:
    """Input for the scheduled-report delivery sweep (no args; scans all due)."""

    pass


@dataclass
class CleanupExpiredExportsInput:
    """Input for the expired-export cleanup sweep (no args)."""

    pass


# =============================================================================
# DATA GATHERING
# =============================================================================

async def _build_export_data(job, db) -> dict:
    """Assemble the payload for an export job based on its type and config.

    Returns a dict the ExportService formatters can serialize. Raises on
    unrecoverable problems so the job is marked failed with a clear message.
    """
    from aexy.schemas.analytics import DateRange
    from aexy.services.analytics_dashboard import AnalyticsDashboardService
    from aexy.services.report_builder import ReportBuilderService

    config = job.config or {}
    developer_ids = config.get("developer_ids") or []
    days = int(config.get("days", 30))

    if job.export_type == "report":
        report_id = config.get("report_id")
        if not report_id:
            raise ValueError("Report export requires config.report_id")
        builder = ReportBuilderService()
        data = await builder.get_report_data(
            report_id=report_id,
            db=db,
            user_id=job.requested_by,
            developer_ids=developer_ids or None,
        )
        if "error" in data:
            raise ValueError(data["error"])
        return data

    dashboard = AnalyticsDashboardService()
    date_range = DateRange(
        start_date=datetime.utcnow() - timedelta(days=days),
        end_date=datetime.utcnow(),
    )

    if job.export_type == "developer_profile":
        developer_id = config.get("developer_id")
        if not developer_id:
            raise ValueError("Developer profile export requires config.developer_id")
        trends = await dashboard.get_productivity_trends(
            developer_ids=[developer_id], db=db, date_range=date_range
        )
        workload = await dashboard.get_workload_distribution(
            developer_ids=[developer_id], db=db, days=days
        )
        return {
            "export_type": "developer_profile",
            "developer_id": developer_id,
            "generated_at": datetime.utcnow().isoformat(),
            "productivity_trends": trends.model_dump() if hasattr(trends, "model_dump") else trends,
            "workload": workload.model_dump() if hasattr(workload, "model_dump") else workload,
        }

    if job.export_type == "team_analytics":
        if not developer_ids:
            raise ValueError("Team analytics export requires config.developer_ids")
        trends = await dashboard.get_productivity_trends(
            developer_ids=developer_ids, db=db, date_range=date_range
        )
        workload = await dashboard.get_workload_distribution(
            developer_ids=developer_ids, db=db, days=days
        )
        return {
            "export_type": "team_analytics",
            "developer_ids": developer_ids,
            "generated_at": datetime.utcnow().isoformat(),
            "productivity_trends": trends.model_dump() if hasattr(trends, "model_dump") else trends,
            "workload": workload.model_dump() if hasattr(workload, "model_dump") else workload,
        }

    raise ValueError(f"Unsupported export_type: {job.export_type}")


# =============================================================================
# ACTIVITIES
# =============================================================================

@activity.defn(name="process_export_job")
async def process_export_job(input: ProcessExportInput) -> dict:
    """Gather data for an export job and render it to a file.

    Moves the job pending -> processing -> completed/failed. Idempotent-ish:
    if the job is already completed it is left untouched.
    """
    from aexy.services.export_service import ExportService

    logger.info("Processing export job %s", input.job_id)
    service = ExportService()

    async with async_session_maker() as db:
        job = await service.get_export_job(input.job_id, db)
        if not job:
            logger.warning("Export job %s not found", input.job_id)
            return {"job_id": input.job_id, "status": "not_found"}
        if job.status == "completed":
            return {"job_id": input.job_id, "status": "completed"}

        data = await _build_export_data(job, db)
        result = await service.process_export(input.job_id, db, data)
        return {
            "job_id": input.job_id,
            "status": result.status if result else "failed",
            "file_path": result.file_path if result else None,
        }


@activity.defn(name="deliver_scheduled_reports")
async def deliver_scheduled_reports(input: DeliverScheduledReportsInput) -> dict:
    """Find due scheduled reports, render each, deliver, and reschedule."""
    from aexy.schemas.analytics import ExportFormat, ExportRequest, ExportType
    from aexy.services.export_service import ExportService
    from aexy.services.report_builder import ReportBuilderService

    builder = ReportBuilderService()
    export_service = ExportService()

    delivered = 0
    failed = 0

    async with async_session_maker() as db:
        due = await builder.get_due_schedules(db)
        logger.info("Found %d due scheduled report(s)", len(due))

        for schedule in due:
            try:
                report = await builder.get_report(schedule.report_id, db, user_id=None)
                report_data = await builder.get_report_data(
                    report_id=schedule.report_id,
                    db=db,
                    user_id=report.creator_id if report else None,
                )
                if "error" in report_data:
                    raise ValueError(report_data["error"])

                # Render the report to the requested format via an export job.
                fmt = ExportFormat(schedule.export_format)
                job = await export_service.create_export_job(
                    request=ExportRequest(
                        export_type=ExportType.REPORT,
                        format=fmt,
                        config={"report_id": schedule.report_id},
                    ),
                    requester_id=report.creator_id if report else schedule.report_id,
                    db=db,
                )
                await export_service.process_export(job.id, db, report_data)

                await _deliver_report(schedule, report, job, db)
                await builder.mark_schedule_run(schedule.id, db)
                delivered += 1
            except Exception:
                logger.exception(
                    "Failed to deliver scheduled report %s", schedule.id
                )
                failed += 1

    return {"delivered": delivered, "failed": failed, "due": delivered + failed}


async def _deliver_report(schedule, report, job, db) -> None:
    """Deliver a rendered report via the schedule's delivery method(s)."""
    method = schedule.delivery_method
    report_name = report.name if report else "Report"

    if method in ("email", "both"):
        try:
            await _deliver_via_email(schedule, report_name, job)
        except Exception:
            logger.exception("Email delivery failed for schedule %s", schedule.id)

    if method in ("slack", "both"):
        try:
            await _deliver_via_slack(schedule, report_name, db)
        except Exception:
            logger.exception("Slack delivery failed for schedule %s", schedule.id)


async def _deliver_via_email(schedule, report_name: str, job) -> None:
    """Send the rendered report to the schedule's recipients over email."""
    recipients = schedule.recipients or []
    if not recipients:
        logger.info("Schedule %s has no email recipients; skipping", schedule.id)
        return

    from aexy.services.email_service import EmailService

    email_service = EmailService()
    if not email_service.is_configured:
        logger.warning(
            "Email service not configured; cannot deliver report for schedule %s",
            schedule.id,
        )
        return

    subject = f"Your scheduled report: {report_name}"
    body_text = (
        f"Your scheduled report '{report_name}' is ready ({job.format.upper()}).\n\n"
        f"It was generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}."
    )
    for recipient in recipients:
        # _send_email routes to the configured provider (Postmark/SMTP/SES).
        await email_service._send_email(recipient, subject, body_text, "")


async def _deliver_via_slack(schedule, report_name: str, db) -> None:
    """Post a report-available notification to the workspace's Slack channel."""
    from sqlalchemy import select

    from aexy.models.integrations import SlackIntegration as SlackIntegrationModel
    from aexy.services.slack_integration import SlackIntegrationService

    result = await db.execute(select(SlackIntegrationModel).limit(1))
    integration = result.scalar_one_or_none()
    if not integration:
        logger.info("No Slack integration configured; skipping Slack delivery")
        return

    service = SlackIntegrationService()
    await service.send_report_notification(
        integration=integration,
        report_name=report_name,
        report_url="",
        db=db,
    )


@activity.defn(name="cleanup_expired_exports")
async def cleanup_expired_exports(input: CleanupExpiredExportsInput) -> dict:
    """Delete expired export jobs and their files."""
    from aexy.services.export_service import ExportService

    service = ExportService()
    async with async_session_maker() as db:
        count = await service.cleanup_expired_exports(db)
    logger.info("Cleaned up %d expired export job(s)", count)
    return {"cleaned": count}
