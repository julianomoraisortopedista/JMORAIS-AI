from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol
from uuid import uuid4

from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, ClaimSupport, SupportState, hash_payload
from jmoraIs.scientific_domain import ScientificArticle, VerificationStatus, utc_now
from jmoraIs.verification import CitationVerificationGate


class EvidencePackageError(RuntimeError):
    pass


class EvidencePackageRejected(EvidencePackageError):
    pass


class EvidencePackageNotFound(EvidencePackageError):
    pass


class EvidencePackageIntegrityError(EvidencePackageError):
    pass


class EvidencePackageExpired(EvidencePackageError):
    pass


class EvidencePackageRevoked(EvidencePackageError):
    def __init__(self, package_id: str, lifecycle: "PackageLifecycle") -> None:
        self.package_id = package_id
        self.lifecycle = lifecycle
        super().__init__(f"evidence package is {lifecycle.value}")


class PackageLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class ExpirationPolicy(str, Enum):
    REJECT_EXPIRED = "REJECT_EXPIRED"
    ALLOW_EXPIRED_FOR_REVALIDATION = "ALLOW_EXPIRED_FOR_REVALIDATION"


@dataclass(frozen=True)
class PublicationIdentity:
    article_id: str
    pmid: Optional[str]
    doi: Optional[str]
    pmcid: Optional[str]
    metadata_hash: str


def publication_metadata_hash(article: ScientificArticle) -> str:
    """Bind an issued package to the exact reconciled bibliographic record."""
    return hash_payload(
        {
            "article_id": article.article_id,
            "title": article.title,
            "authors": list(article.authors),
            "journal": article.journal,
            "journal_abbreviation": article.journal_abbreviation,
            "publication_year": article.publication_year,
            "volume": article.volume,
            "issue": article.issue,
            "pages": article.pages,
            "doi": article.doi,
            "pmid": article.pmid,
            "pmcid": article.pmcid,
            "publication_type": article.publication_type,
            "publisher": article.publisher,
            "publication_place": article.publication_place,
            "book_title": article.book_title,
            "chapter_title": article.chapter_title,
            "editors": list(article.editors),
            "url": article.url,
            "accessed_at": article.accessed_at.isoformat() if article.accessed_at else None,
        }
    )


@dataclass(frozen=True)
class ClaimEvidenceRelationship:
    claim_id: str
    support_id: str
    fragment_id: str
    support_direction: str


@dataclass(frozen=True)
class EvidencePackage:
    package_id: str
    package_version: str
    verification_status: str
    publication_identities: tuple[PublicationIdentity, ...]
    claim_evidence_relationships: tuple[ClaimEvidenceRelationship, ...]
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    verification_references: tuple[str, ...]
    policy_version: str
    pipeline_version: str
    created_at: datetime
    expires_at: Optional[datetime]
    revalidation_required_at: Optional[datetime]
    integrity_hash: str


class LedgerHistoryPort(Protocol):
    def verify_integrity(self, claim_id: Optional[str] = None) -> bool: ...
    def reconstruct(self, claim_id: str, *, as_of: Optional[datetime] = None): ...


@dataclass(frozen=True)
class PackageLedgerAssociation:
    package_id: str
    claim_ids: tuple[str, ...]
    support_ids: tuple[str, ...]
    ledger_event_hashes: tuple[str, ...]


@dataclass(frozen=True)
class PackageCatalogRecord:
    package: EvidencePackage
    association: PackageLedgerAssociation
    ledger: LedgerHistoryPort
    recorded_at: datetime


@dataclass(frozen=True)
class PackageVersionRecord:
    package_id: str
    package_version: str
    integrity_hash: str
    recorded_at: datetime


class PackageCatalogRepository(Protocol):
    """Append-only persistence port; PostgreSQL adapters implement this contract later."""

    def append(self, record: PackageCatalogRecord, version: PackageVersionRecord) -> None: ...
    def get(self, package_id: str) -> Optional[PackageCatalogRecord]: ...
    def version_history(self, package_id: str) -> tuple[PackageVersionRecord, ...]: ...


class ScientificEvidencePackagePort:
    """Sole public boundary for issuing and resolving trusted evidence packages."""

    PACKAGE_VERSION = "ST-04.1"

    def __init__(self, *, catalog: PackageCatalogRepository, clock=utc_now, monitoring=None) -> None:
        self._clock = clock
        self._catalog = catalog
        self._monitoring = monitoring

    def issue(
        self,
        *,
        article: ScientificArticle,
        ledger: AppendOnlyEvidenceLedger,
        claim_id: str,
        support_ids: tuple[str, ...],
        pipeline_version: str,
        expires_at: Optional[datetime] = None,
        revalidation_required_at: Optional[datetime] = None,
    ) -> EvidencePackage:
        if not isinstance(article, ScientificArticle):
            raise EvidencePackageRejected("only ScientificArticle records can be packaged")
        if not isinstance(ledger, AppendOnlyEvidenceLedger):
            raise EvidencePackageRejected("a Scientific Core ledger is required")
        if CitationVerificationGate.evaluate(article) != VerificationStatus.VERIFIED:
            raise EvidencePackageRejected("authoritative VERIFIED status is required")
        record = article.verification_record
        if record is None or not record.search_run_id:
            raise EvidencePackageRejected("verification linkage is required")
        if article.provenance is None or not article.provenance.source_id:
            raise EvidencePackageRejected("provenance linkage is required")
        if not pipeline_version.strip():
            raise EvidencePackageRejected("pipeline_version is required")
        if not support_ids:
            raise EvidencePackageRejected("at least one ledger support is required")

        ledger.verify_integrity(claim_id)
        try:
            snapshot = ledger.reconstruct(claim_id)
        except Exception as exc:
            raise EvidencePackageRejected("claim is absent from the ledger") from exc
        active = {support.support_id: support for support in snapshot.active_supports}
        supports: list[ClaimSupport] = []
        for support_id in support_ids:
            support = active.get(support_id)
            if support is None:
                raise EvidencePackageRejected("ledger support is absent or inactive")
            supports.append(support)

        fragments = {fragment.fragment_id: fragment for fragment in ledger.fragments}
        article_ids = {value for value in (article.pmid, article.doi, article.pmcid) if value}
        if not article_ids:
            raise EvidencePackageRejected("publication identity is required")
        for support in supports:
            fragment = fragments.get(support.fragment_id)
            if fragment is None:
                raise EvidencePackageRejected("ledger fragment is absent")
            fragment_ids = {value for value in (fragment.pmid, fragment.doi, fragment.pmcid) if value}
            if not article_ids.intersection(fragment_ids):
                raise EvidencePackageRejected("ledger evidence does not identify the verified publication")

        created_at = self._clock()
        package_id = uuid4().hex
        relationships = tuple(
            ClaimEvidenceRelationship(
                claim_id=support.claim_id,
                support_id=support.support_id,
                fragment_id=support.fragment_id,
                support_direction=support.support_direction,
            )
            for support in supports
        )
        event_hashes = tuple(event.event_hash for event in snapshot.events)
        verification_refs = tuple(
            hash_payload(
                {
                    "identifier_type": result.identifier_type,
                    "identifier_value": result.identifier_value,
                    "existence_status": result.existence_status,
                    "source_name": result.source_name,
                    "checked_at": result.checked_at.isoformat(),
                }
            )
            for result in record.identifier_results
        ) + (record.search_run_id,)
        unsigned = {
            "package_id": package_id,
            "package_version": self.PACKAGE_VERSION,
            "verification_status": VerificationStatus.VERIFIED.value,
            "publication_identities": [self._identity_dict(article)],
            "relationships": [relationship.__dict__ for relationship in relationships],
            "provenance_references": [article.provenance.source_id],
            "ledger_references": list(event_hashes),
            "verification_references": list(verification_refs),
            "policy_version": record.policy_version,
            "pipeline_version": pipeline_version,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "revalidation_required_at": revalidation_required_at.isoformat() if revalidation_required_at else None,
        }
        package = EvidencePackage(
            package_id=package_id,
            package_version=self.PACKAGE_VERSION,
            verification_status=VerificationStatus.VERIFIED.value,
            publication_identities=(PublicationIdentity(**self._identity_dict(article)),),
            claim_evidence_relationships=relationships,
            provenance_references=(article.provenance.source_id,),
            ledger_references=event_hashes,
            verification_references=verification_refs,
            policy_version=record.policy_version,
            pipeline_version=pipeline_version,
            created_at=created_at,
            expires_at=expires_at,
            revalidation_required_at=revalidation_required_at,
            integrity_hash=hash_payload(unsigned),
        )
        association = PackageLedgerAssociation(
            package_id=package_id,
            claim_ids=tuple(sorted({item.claim_id for item in relationships})),
            support_ids=tuple(item.support_id for item in relationships),
            ledger_event_hashes=event_hashes,
        )
        self._catalog.append(
            PackageCatalogRecord(package=package, association=association, ledger=ledger, recorded_at=created_at),
            PackageVersionRecord(package_id=package_id, package_version=package.package_version, integrity_hash=package.integrity_hash, recorded_at=created_at),
        )
        return package

    def get(
        self,
        package_id: str,
        *,
        expiration_policy: Optional[ExpirationPolicy] = None,
        as_of: Optional[datetime] = None,
    ) -> EvidencePackage:
        if not isinstance(package_id, str):
            raise EvidencePackageRejected("arbitrary evidence objects are not accepted")
        catalog_record = self._catalog.get(package_id)
        if catalog_record is None:
            raise EvidencePackageNotFound("evidence package does not exist")
        package = catalog_record.package
        if package.integrity_hash != hash_payload(self._unsigned(package)):
            if self._monitoring is not None:
                self._monitoring.package_integrity_failure(package_id)
            raise EvidencePackageIntegrityError("evidence package integrity check failed")
        lifecycle = self.lifecycle(package_id, as_of=as_of)
        if lifecycle in {
            PackageLifecycle.RETRACTED,
            PackageLifecycle.INVALIDATED,
            PackageLifecycle.SUPERSEDED,
        }:
            raise EvidencePackageRevoked(package_id, lifecycle)
        if lifecycle == PackageLifecycle.EXPIRED:
            if expiration_policy is None:
                raise EvidencePackageExpired("expired package requires an explicit policy")
            if expiration_policy == ExpirationPolicy.REJECT_EXPIRED:
                raise EvidencePackageExpired("expired package is rejected by policy")
            if expiration_policy != ExpirationPolicy.ALLOW_EXPIRED_FOR_REVALIDATION:
                raise EvidencePackageExpired("unsupported expiration policy")
        return package

    def lifecycle(
        self,
        package_id: str,
        *,
        as_of: Optional[datetime] = None,
    ) -> PackageLifecycle:
        catalog_record = self._catalog.get(package_id)
        if catalog_record is None:
            raise EvidencePackageNotFound("evidence package does not exist")
        package = catalog_record.package
        ledger = catalog_record.ledger
        evaluation_time = as_of or self._clock()
        if evaluation_time < package.created_at:
            raise EvidencePackageNotFound("evidence package did not exist at requested time")
        ledger.verify_integrity()
        relationships_by_claim: dict[str, set[str]] = {}
        for relationship in package.claim_evidence_relationships:
            relationships_by_claim.setdefault(relationship.claim_id, set()).add(relationship.support_id)

        observed_states: set[str] = set()
        for claim_id, support_ids in relationships_by_claim.items():
            snapshot = ledger.reconstruct(claim_id, as_of=evaluation_time)
            state_map = dict(snapshot.support_states)
            observed_states.update(state_map.get(support_id, "MISSING") for support_id in support_ids)

        if SupportState.RETRACTED.value in observed_states:
            lifecycle = PackageLifecycle.RETRACTED
        elif SupportState.INVALIDATED.value in observed_states or "MISSING" in observed_states:
            lifecycle = PackageLifecycle.INVALIDATED
        elif observed_states.intersection({SupportState.SUPERSEDED.value, SupportState.CORRECTED.value}):
            lifecycle = PackageLifecycle.SUPERSEDED
        else:
            deadlines = [deadline for deadline in (package.expires_at, package.revalidation_required_at) if deadline]
            lifecycle = PackageLifecycle.EXPIRED if deadlines and evaluation_time >= min(deadlines) else PackageLifecycle.ACTIVE

        return lifecycle

    @staticmethod
    def _identity_dict(article: ScientificArticle) -> dict[str, Optional[str]]:
        return {
            "article_id": article.article_id,
            "pmid": article.pmid,
            "doi": article.doi,
            "pmcid": article.pmcid,
            "metadata_hash": publication_metadata_hash(article),
        }

    @staticmethod
    def _unsigned(package: EvidencePackage) -> dict[str, object]:
        return {
            "package_id": package.package_id,
            "package_version": package.package_version,
            "verification_status": package.verification_status,
            "publication_identities": [identity.__dict__ for identity in package.publication_identities],
            "relationships": [relationship.__dict__ for relationship in package.claim_evidence_relationships],
            "provenance_references": list(package.provenance_references),
            "ledger_references": list(package.ledger_references),
            "verification_references": list(package.verification_references),
            "policy_version": package.policy_version,
            "pipeline_version": package.pipeline_version,
            "created_at": package.created_at.isoformat(),
            "expires_at": package.expires_at.isoformat() if package.expires_at else None,
            "revalidation_required_at": package.revalidation_required_at.isoformat() if package.revalidation_required_at else None,
        }
