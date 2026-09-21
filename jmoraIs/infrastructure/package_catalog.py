from __future__ import annotations

from jmoraIs.application.evidence_packages import (
    PackageCatalogRecord,
    PackageVersionRecord,
)


class PackageCatalogConflict(RuntimeError):
    pass


class InMemoryPackageCatalogRepository:
    """Append-only reference adapter; replaceable by a PostgreSQL implementation."""

    def __init__(self) -> None:
        self._records: dict[str, PackageCatalogRecord] = {}
        self._versions: list[PackageVersionRecord] = []

    def append(self, record, version) -> None:
        package_id = record.package.package_id
        if package_id in self._records:
            raise PackageCatalogConflict("package catalog records cannot be overwritten")
        if record.association.package_id != package_id:
            raise PackageCatalogConflict("ledger association package_id mismatch")
        if tuple(record.package.ledger_references) != record.association.ledger_event_hashes:
            raise PackageCatalogConflict("ledger association integrity mismatch")
        self._records[package_id] = record
        self._versions.append(version)

    def get(self, package_id):
        return self._records.get(package_id)

    def version_history(self, package_id):
        return tuple(item for item in self._versions if item.package_id == package_id)
