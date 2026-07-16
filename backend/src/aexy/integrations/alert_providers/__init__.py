"""Inbound alert provider adapters.

Each adapter normalizes a provider's webhook payload into the shared
:class:`AlertContext`, so the ingestion service (fingerprint → route → dedup)
stays provider-agnostic. Add a new provider by dropping in a module here and
registering it in ``ADAPTERS``.
"""

from aexy.integrations.alert_providers.base import AlertContext, AlertProviderAdapter
from aexy.integrations.alert_providers.openobserve import OpenObserveAdapter

# provider slug -> adapter
ADAPTERS: dict[str, AlertProviderAdapter] = {
    "openobserve": OpenObserveAdapter(),
}


def get_adapter(provider: str) -> AlertProviderAdapter:
    """Return the adapter for a provider slug, falling back to OpenObserve."""
    return ADAPTERS.get(provider, ADAPTERS["openobserve"])


__all__ = ["AlertContext", "AlertProviderAdapter", "get_adapter", "ADAPTERS"]
