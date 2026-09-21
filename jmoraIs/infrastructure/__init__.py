"""Infrastructure adapters for Scientific Core application ports."""

from .package_catalog import InMemoryPackageCatalogRepository
from .postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from .cryptographic_replay import (
    PostgreSQLCryptographicReplayEngine, ReplayIntegrityReport,
    ReplayIntegrityStatus, StreamReplayReport,
)
from .persisted_gateway_input import (
    InMemoryPersistedGatewayInputRepository,
    PersistedGatewayInputTrustService,
    PostgreSQLPersistedGatewayInputRepository,
)
from .integrity_alerts import InMemoryIntegrityAlertAdapter
from .scientific_citation_persistence import (
    InMemoryScientificCitationRepository, PostgreSQLScientificCitationRepository,
)

__all__ = [
    "InMemoryPackageCatalogRepository", "PostgreSQLCanonicalLedger",
    "PostgreSQLPackageCatalogRepository", "PostgreSQLCryptographicReplayEngine",
    "ReplayIntegrityReport", "ReplayIntegrityStatus", "StreamReplayReport",
    "InMemoryIntegrityAlertAdapter",
    "InMemoryScientificCitationRepository", "PostgreSQLScientificCitationRepository",
    "InMemoryPersistedGatewayInputRepository", "PersistedGatewayInputTrustService",
    "PostgreSQLPersistedGatewayInputRepository",
]
