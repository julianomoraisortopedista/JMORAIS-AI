from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Mapping
from typing import Optional, Protocol

from jmoraIs.application.evidence_packages import EvidencePackage, ScientificEvidencePackagePort
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger

from jmoraIs.scientific_domain import (
    DeduplicationDecision,
    EligibleEvidenceResult,
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    ScientificArticle,
    SearchRun,
    SourceProvenance,
    utc_now,
)
from jmoraIs.verification import (
    CitationVerificationGate,
    decide_publication_verification,
    deduplicate_articles,
    normalize_article,
    normalize_doi,
)


class PubMedVerificationPort(Protocol):
    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult: ...

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult: ...

    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]: ...


class CrossrefVerificationPort(Protocol):
    def search_by_doi(self, doi: str) -> IdentifierVerificationResult: ...


@dataclass(frozen=True)
class ScientificVerificationInput:
    query: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None

    def __post_init__(self) -> None:
        supplied = [bool(self.query and self.query.strip()), bool(self.pmid and self.pmid.strip()), bool(self.doi and self.doi.strip())]
        if sum(supplied) != 1:
            raise ValueError("Provide exactly one of query, pmid, or doi")


@dataclass(frozen=True)
class DiscoveryArticle:
    article_id: str
    title: str
    pmid: Optional[str]
    doi: Optional[str]
    pmcid: Optional[str]


@dataclass(frozen=True)
class ScientificDiscoveryResult:
    search_id: str
    articles: tuple[DiscoveryArticle, ...]
    trusted_evidence: bool = False


class TrustedEvidenceIssuanceError(RuntimeError):
    pass


class AuthoritativeReconciliationPipeline:
    """The only application use case allowed to emit eligible scientific evidence."""

    def __init__(
        self,
        *,
        pubmed: PubMedVerificationPort,
        crossref: CrossrefVerificationPort,
        packages: Optional[ScientificEvidencePackagePort] = None,
        clock=utc_now,
    ) -> None:
        self._pubmed = pubmed
        self._crossref = crossref
        self._packages = packages
        self._clock = clock

    def discover(self, request: ScientificVerificationInput) -> ScientificDiscoveryResult:
        result = self._execute_internal(request)
        return ScientificDiscoveryResult(
            search_id=result.search_run.search_id,
            articles=tuple(
                DiscoveryArticle(
                    article_id=article.article_id,
                    title=article.title,
                    pmid=article.pmid,
                    doi=article.doi,
                    pmcid=article.pmcid,
                )
                for article in result.articles
            ),
        )

    def issue_trusted(
        self,
        request: ScientificVerificationInput,
        *,
        ledger: AppendOnlyEvidenceLedger,
        claim_id: str,
        support_ids: tuple[str, ...],
        pipeline_version: str,
    ) -> tuple[EvidencePackage, ...]:
        if self._packages is None:
            raise TrustedEvidenceIssuanceError("EvidencePackage port is not configured")
        result = self._execute_internal(request)
        if not result.eligible_articles:
            raise TrustedEvidenceIssuanceError("no verified evidence is eligible for package issuance")
        return tuple(
            self._packages.issue(
                article=article,
                ledger=ledger,
                claim_id=claim_id,
                support_ids=support_ids,
                pipeline_version=pipeline_version,
            )
            for article in result.eligible_articles
        )

    def _execute_internal(self, request: ScientificVerificationInput) -> EligibleEvidenceResult:
        """Internal reconciliation result; never a trusted boundary return type."""
        started_at = self._clock()
        search_run = SearchRun(
            query=request.query or request.pmid or request.doi or "",
            source="pubmed",
            result_count=0,
            retrieved_at=started_at,
            status="RUNNING",
        )

        primary_results = self._retrieve_primary(request)
        articles = [
            self._reconcile_primary(result, request, search_run.search_id)
            for result in primary_results
        ]
        deduplicated, raw_decisions = deduplicate_articles(articles)
        decisions = self._trace_decisions(articles, raw_decisions)
        eligible = [article for article in deduplicated if CitationVerificationGate.can_render_trusted(article)]

        search_run.result_count = len(articles)
        search_run.status = "COMPLETED" if all(
            result.existence_status not in {
                ExistenceVerificationStatus.SOURCE_UNAVAILABLE.value,
                ExistenceVerificationStatus.TIMEOUT.value,
                ExistenceVerificationStatus.INVALID_RESPONSE.value,
            }
            for article in articles
            for result in (article.verification_record.identifier_results if article.verification_record else [])
        ) else "DEGRADED"
        return EligibleEvidenceResult(
            search_run=search_run,
            articles=articles,
            eligible_articles=eligible,
            deduplication_decisions=decisions,
            completed_at=self._clock(),
        )

    def _retrieve_primary(
        self, request: ScientificVerificationInput
    ) -> list[IdentifierVerificationResult]:
        if request.pmid:
            return [self._pubmed.search_by_pmid(request.pmid.strip())]
        if request.doi:
            return [self._pubmed.search_by_doi(request.doi.strip())]
        return self._pubmed.search_by_title((request.query or "").strip())

    def _reconcile_primary(
        self,
        primary: IdentifierVerificationResult,
        request: ScientificVerificationInput,
        search_run_id: str,
    ) -> ScientificArticle:
        metadata = dict(primary.authoritative_metadata or {})
        if request.pmid and not metadata.get("pmid"):
            metadata["pmid"] = request.pmid.strip()
        if request.doi and not metadata.get("doi"):
            metadata["doi"] = normalize_doi(request.doi)

        article = normalize_article(
            {
                **metadata,
                "source": "pubmed",
                "source_locator": primary.source_locator,
            }
        )
        article.provenance = SourceProvenance(
            source_type="pubmed",
            source_database="pubmed",
            source_name=primary.source_name or "NCBI PubMed",
            source_locator=primary.source_locator,
            retrieved_at=primary.checked_at,
            raw_payload=dict(primary.raw_outcome) if isinstance(primary.raw_outcome, Mapping) else {"outcome": primary.raw_outcome},
        )

        results = [primary]
        doi = normalize_doi(article.doi or request.doi)
        if doi:
            article.doi = doi
            results.append(self._crossref.search_by_doi(doi))

        return decide_publication_verification(
            article,
            results,
            checked_at=self._clock(),
            policy_version="ST-02",
            search_run_id=search_run_id,
        )

    @staticmethod
    def _trace_decisions(
        articles: list[ScientificArticle], raw_decisions: list[dict[str, object]]
    ) -> list[DeduplicationDecision]:
        by_id = {article.article_id: article for article in articles}
        decisions: list[DeduplicationDecision] = []
        for raw in raw_decisions:
            kept_id = str(raw["kept_article_id"])
            duplicate_id = str(raw["dropped_article_id"])
            kept = by_id.get(kept_id)
            duplicate = by_id.get(duplicate_id)
            decisions.append(
                DeduplicationDecision(
                    deduplication_key=str(raw["key"]),
                    kept_article_id=kept_id,
                    duplicate_article_id=duplicate_id,
                    reason=str(raw["reason"]),
                    conflicting_values=dict(raw.get("conflicting_values") or {}),
                    kept_provenance_id=kept.provenance.source_id if kept and kept.provenance else None,
                    duplicate_provenance_id=(
                        duplicate.provenance.source_id if duplicate and duplicate.provenance else None
                    ),
                )
            )
        return decisions
