"""CRUD + secret management for alert integrations."""

import secrets
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.encryption import decrypt_credentials, encrypt_credentials
from aexy.models.alerting import AlertEvent, AlertIntegration
from aexy.schemas.alerting import AlertIntegrationCreate, AlertIntegrationUpdate


class AlertIntegrationService:
    """Manage alert integrations and their inbound tokens/secrets."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, workspace_id: str, data: AlertIntegrationCreate) -> tuple[AlertIntegration, str]:
        """Create an integration. Returns (integration, plaintext_signing_secret)."""
        signing_secret = secrets.token_urlsafe(32)
        integration = AlertIntegration(
            id=str(uuid4()),
            workspace_id=workspace_id,
            provider=data.provider,
            name=data.name,
            inbound_token=secrets.token_urlsafe(24),
            signing_secret=encrypt_credentials({"secret": signing_secret}),
            base_url=data.base_url,
            default_form_id=data.default_form_id,
            routing_rules=[r.model_dump() for r in data.routing_rules],
            fingerprint_template=data.fingerprint_template,
            dedup_window_minutes=data.dedup_window_minutes,
            comment_throttle_minutes=data.comment_throttle_minutes,
            auto_resolve=data.auto_resolve,
        )
        self.db.add(integration)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration, signing_secret

    async def list_integrations(self, workspace_id: str) -> list[AlertIntegration]:
        stmt = (
            select(AlertIntegration)
            .where(AlertIntegration.workspace_id == workspace_id)
            .order_by(AlertIntegration.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, workspace_id: str, integration_id: str) -> AlertIntegration | None:
        stmt = select(AlertIntegration).where(
            and_(AlertIntegration.id == integration_id, AlertIntegration.workspace_id == workspace_id)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_token(self, inbound_token: str) -> AlertIntegration | None:
        stmt = select(AlertIntegration).where(AlertIntegration.inbound_token == inbound_token)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def update(self, integration: AlertIntegration, data: AlertIntegrationUpdate) -> AlertIntegration:
        payload = data.model_dump(exclude_unset=True)
        if "routing_rules" in payload and payload["routing_rules"] is not None:
            payload["routing_rules"] = [
                r.model_dump() if hasattr(r, "model_dump") else r for r in data.routing_rules
            ]
        for key, value in payload.items():
            setattr(integration, key, value)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration

    async def rotate_secret(self, integration: AlertIntegration) -> str:
        signing_secret = secrets.token_urlsafe(32)
        integration.signing_secret = encrypt_credentials({"secret": signing_secret})
        await self.db.flush()
        return signing_secret

    async def delete(self, integration: AlertIntegration) -> None:
        await self.db.delete(integration)
        await self.db.flush()

    async def list_events(
        self, workspace_id: str, integration_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[AlertEvent], int]:
        base = select(AlertEvent).where(
            and_(AlertEvent.workspace_id == workspace_id, AlertEvent.integration_id == integration_id)
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        rows = (
            await self.db.execute(
                base.order_by(AlertEvent.received_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
        return list(rows), total

    @staticmethod
    def signing_secret_plaintext(integration: AlertIntegration) -> str | None:
        """Decrypt and return the stored signing secret."""
        return decrypt_credentials(integration.signing_secret or {}).get("secret")
