"""Application use cases exposed by the Scientific Core trust boundary."""

from .scientific_verification import DiscoveryArticle, ScientificDiscoveryResult
from .evidence_packages import (
    EvidencePackage,
    EvidencePackageExpired,
    EvidencePackageIntegrityError,
    EvidencePackageNotFound,
    EvidencePackageRejected,
    EvidencePackageRevoked,
    ExpirationPolicy,
    PackageLifecycle,
    PackageCatalogRepository,
    ScientificEvidencePackagePort,
)
from .ports import EvidencePackageQueryPort
from .integrity_alerts import (
    IntegrityAlert, IntegrityAlertPort, IntegrityAlertType, IntegrityMonitoringService,
)
from .scientific_citations import (
    ReconciledBibliographicMetadata, ScientificCitationRecord,
    ScientificCitationRepository, ScientificCitationQueryPort, ScientificCitationService,
)

__all__ = [
    "DiscoveryArticle", "ScientificDiscoveryResult",
    "EvidencePackage", "EvidencePackageExpired", "EvidencePackageIntegrityError",
    "EvidencePackageNotFound", "EvidencePackageRejected", "ExpirationPolicy",
    "EvidencePackageRevoked", "PackageLifecycle",
    "PackageCatalogRepository",
    "ScientificEvidencePackagePort",
    "EvidencePackageQueryPort",
    "IntegrityAlert", "IntegrityAlertPort", "IntegrityAlertType", "IntegrityMonitoringService",
    "ReconciledBibliographicMetadata", "ScientificCitationRecord",
    "ScientificCitationRepository", "ScientificCitationQueryPort", "ScientificCitationService",
]
