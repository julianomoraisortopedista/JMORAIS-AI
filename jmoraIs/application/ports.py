from __future__ import annotations

from typing import Protocol

from .evidence_packages import EvidencePackage


class EvidencePackageQueryPort(Protocol):
    """Canonical read port for a currently valid scientific EvidencePackage."""

    def get(self, package_id: str) -> EvidencePackage: ...
