from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import text


class ReplayIntegrityStatus(str, Enum):
    VALID = "VALID"
    TAMPERED = "TAMPERED"


@dataclass(frozen=True)
class ReplayFailure:
    event_id: str
    position: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StreamReplayReport:
    stream: str
    verified_events: tuple[str, ...]
    failed_events: tuple[ReplayFailure, ...]
    broken_chains: tuple[str, ...]
    tampered_events: tuple[str, ...]
    completeness_verified: bool
    integrity_status: ReplayIntegrityStatus
    checkpoint_found: bool | None = None
    expected_records: int | None = None
    observed_records: int | None = None
    expected_head_hash: str | None = None
    observed_head_hash: str | None = None


@dataclass(frozen=True)
class ReplayIntegrityReport:
    streams: tuple[StreamReplayReport, ...]
    verified_events: int
    failed_events: int
    broken_chains: int
    integrity_status: ReplayIntegrityStatus
    overall_decision: ReplayIntegrityStatus


@dataclass(frozen=True)
class _StreamDefinition:
    table: str
    owner: str
    kind: str

@dataclass(frozen=True)
class _TrustStreamDefinition:
    table: str
    owner: str
    event_id: str
    previous_hash: str
    event_hash: str
    kind: str


_EVENT_STREAMS = (
    _StreamDefinition("canonical_ledger_events", "claim_id", "scientific"),
    _StreamDefinition("governed_clinical_audit_events", "case_id", "audit"),
    _StreamDefinition("clinical_conflict_adjudication_events", "conflict_id", "conflict"),
    _StreamDefinition("governed_evidence_lifecycle_events", "governed_evidence_id", "lifecycle"),
)

_MANDATORY_TRUST_STREAMS = (
    _TrustStreamDefinition("governed_llm_draft_lifecycle_events","draft_id","lifecycle_event_id","previous_hash","integrity_hash","draft_lifecycle"),
    _TrustStreamDefinition("llm_human_review_events","draft_id","review_event_id","previous_hash","integrity_hash","human_review"),
    _TrustStreamDefinition("llm_human_review_security_events","correlation_id","event_id","previous_hash","integrity_hash","review_security"),
)

_TRUST_ROW_FIELDS = {
    "draft_lifecycle": (
        "draft_version", "prior_status", "resulting_status", "reason_reference",
        "actor_reference", "policy_version", "predecessor_event_id",
    ),
    "human_review": (
        "draft_version", "invocation_id", "request_id", "correlation_id",
        "organization_id", "prior_state", "resulting_state", "decision",
        "reviewer_id", "reviewer_role", "policy_version",
        "predecessor_event_id",
    ),
    "review_security": (
        "event_type", "draft_id", "draft_version", "invocation_id", "request_id",
        "principal_id", "reviewer_id", "reviewer_role", "organization_id",
        "result", "reason_code", "policy_version",
    ),
}

def _hash(payload: Any, *, ensure_ascii: bool = True) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_ascii, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PostgreSQLCryptographicReplayEngine:
    """Read-only replay that distrusts stored hashes and independently recomputes them."""

    def __init__(self, engine, *, monitoring=None) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("cryptographic persistent replay requires PostgreSQL")
        self._engine = engine
        self._monitoring = monitoring

    def replay_all(self) -> ReplayIntegrityReport:
        reports: list[StreamReplayReport] = []
        for definition in _EVENT_STREAMS:
            with self._engine.connect() as connection:
                owners = connection.execute(text(
                    f"SELECT DISTINCT {definition.owner} FROM {definition.table} ORDER BY {definition.owner}"
                )).scalars().all()
            reports.extend(self.replay_stream(definition.table, owner) for owner in owners)
        with self._engine.connect() as connection:
            packages = connection.execute(text(
                "SELECT DISTINCT evidence_package_id FROM governed_evidence_versions ORDER BY evidence_package_id"
            )).scalars().all()
        reports.extend(self.replay_governed_evidence(package_id) for package_id in packages)
        with self._engine.connect() as connection:
            evidence_packages = connection.execute(text(
                "SELECT package_id FROM evidence_package_catalog ORDER BY package_id"
            )).scalars().all()
        reports.extend(self.replay_evidence_package(package_id) for package_id in evidence_packages)
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("""SELECT stream_id FROM cryptographic_stream_checkpoints
                  WHERE stream_namespace='persisted_gateway_inputs' ORDER BY checkpoint_id""")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,persisted_gateway_input_id FROM persisted_gateway_inputs ORDER BY sequence_id")).all()
            expected={value for value in checkpoints}
            actual={self._checkpoint_id(tenant,identifier) for tenant,identifier in rows}
            registry=expected|actual
            if not registry:
                reports.append(self._report("mandatory_family:persisted_gateway_inputs",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:
                    reports.append(self._report("persisted_gateway_inputs:"+stream_id,(),
                        (ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)))
                    continue
                tenant_id,identifier=stream_id.rsplit("|",1)
                reports.append(self.replay_persisted_gateway_input(identifier,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:persisted_gateway_inputs",(),(ReplayFailure("persisted_gateway_inputs",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("""SELECT stream_id FROM cryptographic_stream_checkpoints
                  WHERE stream_namespace='governed_evidence_persisted_references' ORDER BY checkpoint_id""")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM governed_evidence_persisted_references ORDER BY sequence_id")).all()
            expected=set(checkpoints);actual={f"{tenant}|{identifier}" for tenant,identifier in rows}
            registry=expected|actual
            if not registry:reports.append(self._report("mandatory_family:governed_evidence_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("governed_evidence_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1)
                reports.append(self.replay_governed_evidence_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:governed_evidence_persisted_references",(),(ReplayFailure("governed_evidence_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("""SELECT stream_id FROM cryptographic_stream_checkpoints
                  WHERE stream_namespace='llm_invocation_persisted_references' ORDER BY checkpoint_id""")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM llm_invocation_persisted_references ORDER BY sequence_id")).all()
            registry=set(checkpoints)|{f"{tenant}|{identifier}" for tenant,identifier in rows}
            if not registry:reports.append(self._report("mandatory_family:llm_invocation_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("llm_invocation_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1)
                reports.append(self.replay_llm_invocation_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:llm_invocation_persisted_references",(),(ReplayFailure("llm_invocation_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("SELECT stream_id FROM cryptographic_stream_checkpoints WHERE stream_namespace='medical_document_persisted_references' ORDER BY checkpoint_id")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM medical_document_persisted_references ORDER BY sequence_id")).all()
            registry=set(checkpoints)|{f"{tenant}|{identifier}" for tenant,identifier in rows}
            if not registry:reports.append(self._report("mandatory_family:medical_document_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("medical_document_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1);reports.append(self.replay_medical_document_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:medical_document_persisted_references",(),(ReplayFailure("medical_document_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("SELECT stream_id FROM cryptographic_stream_checkpoints WHERE stream_namespace='human_review_persisted_references' ORDER BY checkpoint_id")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM human_review_persisted_references ORDER BY sequence_id")).all()
            registry=set(checkpoints)|{f"{tenant}|{identifier}" for tenant,identifier in rows}
            if not registry:reports.append(self._report("mandatory_family:human_review_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("human_review_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1);reports.append(self.replay_human_review_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:human_review_persisted_references",(),(ReplayFailure("human_review_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("SELECT stream_id FROM cryptographic_stream_checkpoints WHERE stream_namespace='clinical_reasoning_input_persisted_references' ORDER BY checkpoint_id")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM clinical_reasoning_input_persisted_references ORDER BY sequence_id")).all()
            registry=set(checkpoints)|{f"{tenant}|{identifier}" for tenant,identifier in rows}
            if not registry:reports.append(self._report("mandatory_family:clinical_reasoning_input_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("clinical_reasoning_input_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1);reports.append(self.replay_clinical_reasoning_input_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:clinical_reasoning_input_persisted_references",(),(ReplayFailure("clinical_reasoning_input_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                checkpoints=connection.execute(text("""SELECT stream_id FROM cryptographic_stream_checkpoints
                  WHERE stream_namespace='governed_llm_draft_persisted_references' ORDER BY checkpoint_id""")).scalars().all()
                rows=connection.execute(text("SELECT tenant_id,reference_id FROM governed_llm_draft_persisted_references ORDER BY sequence_id")).all()
            expected=set(checkpoints);actual={f"{tenant}|{identifier}" for tenant,identifier in rows};registry=expected|actual
            if not registry:reports.append(self._report("mandatory_family:governed_llm_draft_persisted_references",(),()))
            for stream_id in sorted(registry):
                if "|" not in stream_id:reports.append(self._report("governed_llm_draft_persisted_references:"+stream_id,(),(ReplayFailure(stream_id,None,("STREAM_COMPLETENESS_FAILURE",)),)));continue
                tenant_id,reference_id=stream_id.rsplit("|",1)
                reports.append(self.replay_governed_llm_draft_reference(reference_id,tenant_id=tenant_id))
        except Exception:
            reports.append(self._report("mandatory_family:governed_llm_draft_persisted_references",(),(ReplayFailure("governed_llm_draft_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        try:
            with self._engine.connect() as connection:
                rows=connection.execute(text("SELECT reference_id FROM audit_defense_persisted_references")).scalars().all()
                anchors=connection.execute(text("SELECT stream_id FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references'")).scalars().all()
            registry=set(rows)|set(anchors)
            if not registry:reports.append(self._report("mandatory_family:audit_defense_persisted_references",(),()))
            for reference_id in sorted(registry):reports.append(self.replay_audit_defense_reference(reference_id))
        except Exception:
            reports.append(self._report("mandatory_family:audit_defense_persisted_references",(),(ReplayFailure("audit_defense_persisted_references",None,("UNVERIFIABLE_STREAM",)),)))
        for definition in _MANDATORY_TRUST_STREAMS:
            try:
                with self._engine.connect() as connection:
                    owners=connection.execute(text(f"SELECT DISTINCT tenant_id,{definition.owner} FROM {definition.table} ORDER BY tenant_id,{definition.owner}")).mappings().all()
                if not owners:
                    reports.append(self._report(f"mandatory_family:{definition.table}",(),()))
                else:
                    reports.extend(self.replay_trust_stream(definition.table,row[definition.owner],tenant_id=row["tenant_id"]) for row in owners)
            except Exception:
                reports.append(self._report(f"mandatory_family:{definition.table}",(),(ReplayFailure(definition.table,None,("UNVERIFIABLE_STREAM",)),)))
        status = ReplayIntegrityStatus.TAMPERED if any(
            report.integrity_status == ReplayIntegrityStatus.TAMPERED for report in reports
        ) else ReplayIntegrityStatus.VALID
        if status == ReplayIntegrityStatus.TAMPERED and self._monitoring is not None:
            self._monitoring.tampered_replay("platform")
        return ReplayIntegrityReport(
            streams=tuple(reports),
            verified_events=sum(len(report.verified_events) for report in reports),
            failed_events=sum(len(report.failed_events) for report in reports),
            broken_chains=sum(len(report.broken_chains) for report in reports),
            integrity_status=status,
            overall_decision=status,
        )

    @staticmethod
    def _audit_defense_reference_hash(row):
        from datetime import timezone
        fields=("sequence_id","reference_id","tenant_id","stream_id","package_version","package_id","policy_version","integrity_hash","issued_at")
        values=[str(row[field]) for field in fields[:-1]]
        values.append(row["issued_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        if row.get("reference_state") is not None:values.append(row["reference_state"])
        return hashlib.sha256("|".join(value.encode("utf-8").hex() for value in values).encode("ascii")).hexdigest()

    def replay_audit_defense_reference(self,reference_id):
        from jmoraIs.audit_defense.persistence import PostgreSQLAuditDefenseRepository,AuditDefenseJsonCodec,_package_integrity,_package_policy,_validate_reference_state
        from jmoraIs.audit_defense.domain import DefenseReferenceState
        reasons=[]
        try:
            with self._engine.connect() as connection:
                row=connection.execute(text("SELECT * FROM audit_defense_persisted_references WHERE reference_id=:id"),{"id":reference_id}).mappings().one_or_none()
                checkpoints=connection.execute(text("SELECT stream_position,head_hash,recorded_at FROM cryptographic_stream_checkpoints WHERE stream_namespace='audit_defense_persisted_references' AND stream_id=:id"),{"id":reference_id}).mappings().all()
                if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
                if not checkpoints:reasons.extend(("MISSING_CHECKPOINT","LEGACY_MISSING_AUDIT_DEFENSE_REFERENCE_CHECKPOINT"))
                elif len(checkpoints)!=1:reasons.append("CONFLICTING_CHECKPOINT")
                if row is not None:
                    computed=self._audit_defense_reference_hash(row)
                    if any(c["stream_position"]!=1 or c["head_hash"]!=computed or c["recorded_at"]!=row["issued_at"] for c in checkpoints):
                        reasons.append("STREAM_COMPLETENESS_FAILURE")
                    owner=PostgreSQLAuditDefenseRepository(self._engine)
                    package=owner._load_exact_package(connection,row["tenant_id"],row["stream_id"],row["package_version"],row["package_id"])
                    if row.get("reference_state") is None:
                        reasons.append("LEGACY_MISSING_DEFENSE_REFERENCE_STATE")
                    else:
                        _validate_reference_state(package,DefenseReferenceState(row["reference_state"]))
                    if _package_integrity(AuditDefenseJsonCodec(),package)!=row["integrity_hash"] or _package_policy(package)!=row["policy_version"] or package.created_at!=row["issued_at"]:
                        reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
        except Exception:reasons.append("UNVERIFIABLE_STREAM")
        failures=(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))),) if reasons else ()
        return self._report("audit_defense_persisted_references:"+reference_id,() if reasons else (reference_id,),failures)

    def replay_governed_evidence_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference,reference_integrity
        stream_id=f"{tenant_id}|{reference_id}";failures=[];verified=[]
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM governed_evidence_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=connection.execute(text("""SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints
              WHERE stream_namespace='governed_evidence_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"""),{"id":stream_id}).mappings().first()
        reasons=[]
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            reference=PersistedGovernedEvidenceReference(row["reference_id"],row["governed_evidence_id"],row["stream_version"],row["tenant_id"],row["evidence_package_id"],row["appraisal_record_id"],row["appraisal_record_version"],row["policy_version"],row["lifecycle_event_id"],row["lifecycle_status"],row["lifecycle_integrity_hash"],row["provenance_reference"],row["governed_evidence_integrity_hash"],row["integrity_hash"],row["issued_at"])
            computed=reference_integrity(reference)
            if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
            if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
        if reasons:failures.append(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))))
        else:verified.append(reference_id)
        return self._report(f"governed_evidence_persisted_references:{stream_id}",tuple(verified),tuple(failures))

    def replay_governed_llm_draft_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.governed_llm_draft.exact_reference import governed_draft_reference_integrity
        from jmoraIs.governed_llm_draft.exact_reference_persistence import PostgreSQLGovernedLLMDraftExactReferenceRepository
        stream_id=f"{tenant_id}|{reference_id}";failures=[];verified=[]
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM governed_llm_draft_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=connection.execute(text("""SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints
              WHERE stream_namespace='governed_llm_draft_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"""),{"id":stream_id}).mappings().first()
        reasons=[]
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            try:
                invocation_reference=None
                invocation_reference_id=row.get("invocation_reference_id")
                if invocation_reference_id:
                    from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
                    with self._engine.connect() as connection:
                        invocation_row=connection.execute(text("SELECT * FROM llm_invocation_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":invocation_reference_id}).mappings().first()
                    if invocation_row is None or invocation_row["integrity_hash"]!=row["invocation_reference_integrity_hash"]:
                        reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
                    else:
                        invocation_reference=PostgreSQLLLMInvocationExactReferenceRepository._decode_reference(invocation_row)
                reference=PostgreSQLGovernedLLMDraftExactReferenceRepository._decode_reference(row,invocation_reference)
                computed=governed_draft_reference_integrity(reference)
                if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
                if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
            except Exception:reasons.append("MODIFIED_PAYLOAD")
        if reasons:failures.append(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))))
        else:verified.append(reference_id)
        return self._report(f"governed_llm_draft_persisted_references:{stream_id}",tuple(verified),tuple(failures))

    def replay_llm_invocation_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.llm_gateway.exact_reference import llm_invocation_reference_integrity
        from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
        stream_id=f"{tenant_id}|{reference_id}";failures=[];verified=[]
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM llm_invocation_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=connection.execute(text("""SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints
              WHERE stream_namespace='llm_invocation_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"""),{"id":stream_id}).mappings().first()
        reasons=[]
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            try:
                reference=PostgreSQLLLMInvocationExactReferenceRepository._decode_reference(row)
                computed=llm_invocation_reference_integrity(reference)
                if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
                if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
            except Exception:reasons.append("MODIFIED_PAYLOAD")
        if reasons:failures.append(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))))
        else:verified.append(reference_id)
        return self._report(f"llm_invocation_persisted_references:{stream_id}",tuple(verified),tuple(failures))

    def replay_medical_document_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.medical_documents.exact_reference import medical_document_reference_integrity
        from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
        stream_id=f"{tenant_id}|{reference_id}";failures=[];verified=[]
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM medical_document_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=connection.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='medical_document_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"),{"id":stream_id}).mappings().first()
            guideline=connection.execute(text("SELECT * FROM guideline_recommendation_set_references WHERE reference_id=:id"),{"id":row["guideline_reference_id"] if row else None}).mappings().first()
            orthopedic=connection.execute(text("SELECT * FROM orthopedic_assessment_set_references WHERE reference_id=:id"),{"id":row["orthopedic_reference_id"] if row else None}).mappings().first()
        reasons=[]
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            try:
                g=PostgreSQLMedicalDocumentExactReferenceRepository._decode_guideline_reference(guideline) if guideline else None
                o=PostgreSQLMedicalDocumentExactReferenceRepository._decode_orthopedic_reference(orthopedic) if orthopedic else None
                reference=PostgreSQLMedicalDocumentExactReferenceRepository._decode_reference(row,g,o);computed=medical_document_reference_integrity(reference)
                if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
                if (row["guideline_reference_id"] and not guideline) or (row["orthopedic_reference_id"] and not orthopedic):reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
                if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
            except Exception:reasons.append("MODIFIED_PAYLOAD")
        if reasons:failures.append(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))))
        else:verified.append(reference_id)
        return self._report(f"medical_document_persisted_references:{stream_id}",tuple(verified),tuple(failures))

    def replay_human_review_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.llm_human_review.exact_reference import human_review_reference_integrity
        from jmoraIs.llm_human_review.exact_reference_persistence import PostgreSQLHumanReviewExactReferenceRepository
        from jmoraIs.governed_llm_draft.exact_reference_persistence import PostgreSQLGovernedLLMDraftExactReferenceRepository
        from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
        stream_id=f"{tenant_id}|{reference_id}";reasons=[];verified=[]
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM human_review_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=c.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='human_review_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"),{"id":stream_id}).mappings().first()
            draft_row=c.execute(text("SELECT * FROM governed_llm_draft_persisted_references WHERE reference_id=:id"),{"id":row["draft_reference_id"] if row else None}).mappings().first()
            invocation_row=c.execute(text("SELECT * FROM llm_invocation_persisted_references WHERE reference_id=:id"),{"id":draft_row["invocation_reference_id"] if draft_row else None}).mappings().first()
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            try:
                if draft_row is None or invocation_row is None:raise ValueError
                invocation=PostgreSQLLLMInvocationExactReferenceRepository._decode_reference(invocation_row)
                draft=PostgreSQLGovernedLLMDraftExactReferenceRepository._decode_reference(draft_row,invocation)
                reference=PostgreSQLHumanReviewExactReferenceRepository._decode_reference(row,draft);computed=human_review_reference_integrity(reference)
                if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
                if draft.integrity_hash!=row["draft_reference_integrity_hash"]:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
                if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
            except Exception:reasons.append("MODIFIED_PAYLOAD")
        failures=(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))),) if reasons else ()
        if not reasons:verified.append(reference_id)
        return self._report(f"human_review_persisted_references:{stream_id}",tuple(verified),failures)

    def replay_clinical_reasoning_input_reference(self,reference_id: str,*,tenant_id: str) -> StreamReplayReport:
        from jmoraIs.reasoning_input.exact_reference import reference_integrity
        from jmoraIs.reasoning_input.exact_reference_persistence import PostgreSQLClinicalReasoningInputExactReferenceRepository
        stream_id=f"{tenant_id}|{reference_id}";reasons=[];verified=[]
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM clinical_reasoning_input_persisted_references WHERE tenant_id=:tenant AND reference_id=:id"),{"tenant":tenant_id,"id":reference_id}).mappings().first()
            checkpoint=c.execute(text("SELECT stream_position,head_hash FROM cryptographic_stream_checkpoints WHERE stream_namespace='clinical_reasoning_input_persisted_references' AND stream_id=:id ORDER BY checkpoint_id DESC LIMIT 1"),{"id":stream_id}).mappings().first()
        if row is None:reasons.append("STREAM_COMPLETENESS_FAILURE")
        if checkpoint is None:reasons.append("MISSING_CHECKPOINT")
        if row is not None:
            try:
                repository=object.__new__(PostgreSQLClinicalReasoningInputExactReferenceRepository);repository._codec=__import__('jmoraIs.reasoning_input.persistence',fromlist=['ReasoningInputJsonCodec']).ReasoningInputJsonCodec()
                reference=repository._decode(row);computed=reference_integrity(reference)
                if computed!=row["integrity_hash"]:reasons.append("HASH_MISMATCH")
                if checkpoint and (checkpoint["stream_position"]!=1 or checkpoint["head_hash"]!=computed):reasons.append("STREAM_COMPLETENESS_FAILURE")
            except Exception:reasons.append("MODIFIED_PAYLOAD")
        failures=(ReplayFailure(reference_id,1,tuple(dict.fromkeys(reasons))),) if reasons else ()
        if not reasons:verified.append(reference_id)
        return self._report(f"clinical_reasoning_input_persisted_references:{stream_id}",tuple(verified),failures)

    def replay_trust_stream(self,table: str,stream_id: str,*,tenant_id: str) -> StreamReplayReport:
        definition=next((item for item in _MANDATORY_TRUST_STREAMS if item.table==table),None)
        if definition is None:raise ValueError("unsupported mandatory trust stream")
        with self._engine.connect() as connection:
            rows=connection.execute(text(f"""SELECT {definition.event_id} AS event_id,{definition.owner} AS owner_id,
                tenant_id,stream_position,{definition.previous_hash} AS previous_event_hash,{definition.event_hash} AS event_hash,
                occurred_at,payload,to_jsonb(source) AS persisted_row
                FROM {definition.table} AS source WHERE tenant_id=:tenant AND {definition.owner}=:owner
                ORDER BY stream_position,sequence_id"""),{"tenant":tenant_id,"owner":stream_id}).mappings().all()
            checkpoint=self._checkpoint(connection,definition.table,self._checkpoint_id(tenant_id,stream_id))
            context=self._trust_reference_context(connection,definition,tenant_id,stream_id)
        return self._verify_trust_rows(definition,tenant_id,stream_id,rows,context,checkpoint)

    def _verify_trust_rows(self,definition,tenant_id,stream_id,rows,context,checkpoint):
        verified=[];failures=[];seen_ids=set();seen_payload_ids=set();seen_hashes=set();seen_positions=set();expected_previous=None;previous_time=None
        for expected_position,row in enumerate(rows,1):
            reasons=[];event_id=str(row["event_id"]);position=row["stream_position"]
            value=self._decode_integrity_payload(row["payload"])
            if position!=expected_position or position in seen_positions:reasons.append("BROKEN_STREAM_POSITION")
            if event_id in seen_ids:reasons.append("DUPLICATE_EVENT")
            seen_ids.add(event_id);seen_positions.add(position)
            if row["tenant_id"]!=tenant_id or row["owner_id"]!=stream_id:reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            if value.get(definition.event_id)!=event_id or value.get(definition.owner)!=stream_id or value.get("tenant_id")!=tenant_id:reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            supplied=value.get("integrity_hash");canonical=dict(value);canonical["integrity_hash"]=""
            recomputed=_hash(canonical)
            payload_event_id=value.get(definition.event_id)
            if payload_event_id in seen_payload_ids or supplied in seen_hashes:reasons.append("DUPLICATE_EVENT")
            seen_payload_ids.add(payload_event_id);seen_hashes.add(supplied)
            if supplied!=row["event_hash"] or recomputed!=row["event_hash"]:reasons.append("MODIFIED_PAYLOAD")
            reasons.extend(self._trust_row_payload_failures(definition,value,row["persisted_row"]))
            if row["previous_event_hash"]!=expected_previous or value.get("previous_hash")!=expected_previous:reasons.append("BROKEN_PREVIOUS_HASH")
            reasons.extend(self._trust_predecessor_failures(definition.kind,value,rows,expected_position))
            timestamp=self._timestamp(value.get("occurred_at") or row["occurred_at"])
            if previous_time and timestamp<previous_time:reasons.append("INVALID_TIMESTAMP_ORDER")
            previous_time=timestamp
            reasons.extend(self._trust_reference_failures(definition.kind,value,context))
            self._record(event_id,position,reasons,verified,failures);expected_previous=recomputed
        self._verify_checkpoint(rows,checkpoint,failures)
        return self._report(f"{definition.table}:{tenant_id}:{stream_id}",verified,failures)

    @staticmethod
    def _trust_row_payload_failures(definition,value,persisted_row):
        reasons=[]
        for field in _TRUST_ROW_FIELDS[definition.kind]:
            if PostgreSQLCryptographicReplayEngine._comparable(value.get(field)) != PostgreSQLCryptographicReplayEngine._comparable(persisted_row.get(field)):
                reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
                break
        return reasons

    @staticmethod
    def _comparable(value):
        if isinstance(value,datetime):return value.isoformat()
        return value

    @staticmethod
    def _checkpoint_id(tenant_id,stream_id):return tenant_id+"|"+stream_id

    @classmethod
    def _decode_integrity_payload(cls,value):
        if isinstance(value,list):return [cls._decode_integrity_payload(x) for x in value]
        if not isinstance(value,dict):return value
        # Domain enums inherit from ``str`` and are therefore serialized by
        # json.dumps as their value (for example ``"ACTIVE"``).  Reconstruct
        # that exact canonical representation rather than ``EnumClass.ACTIVE``.
        if "__enum__" in value:return value["value"]
        if "__datetime__" in value:return datetime.fromisoformat(value["__datetime__"])
        if "__tuple__" in value:return tuple(cls._decode_integrity_payload(x) for x in value["__tuple__"])
        return {k:cls._decode_integrity_payload(v) for k,v in value.items() if k!="__type__"}

    @staticmethod
    def _trust_predecessor_failures(kind,value,rows,position):
        reasons=[];previous=rows[position-2] if position>1 else None
        predecessor=value.get("predecessor_event_id")
        if kind in {"draft_lifecycle","human_review"}:
            expected=str(previous["event_id"]) if previous else None
            if predecessor!=expected:reasons.append("BROKEN_PREDECESSOR_REFERENCE")
        if kind=="draft_lifecycle":
            prior=value.get("prior_status");result=value.get("resulting_status")
            previous_result=None if previous is None else PostgreSQLCryptographicReplayEngine._decode_integrity_payload(previous["payload"]).get("resulting_status")
            if (previous is None and (prior is not None or result!="ACTIVE")) or (previous is not None and prior!=previous_result):reasons.append("BROKEN_VERSION_CHAIN")
        elif kind=="human_review":
            prior=value.get("prior_state");previous_result=None if previous is None else PostgreSQLCryptographicReplayEngine._decode_integrity_payload(previous["payload"]).get("resulting_state")
            if (previous is None and prior!="PENDING_REVIEW") or (previous is not None and prior!=previous_result):reasons.append("BROKEN_VERSION_CHAIN")
        return reasons

    @staticmethod
    def _trust_reference_context(connection,definition,tenant_id,stream_id):
        drafts={row["draft_id"]:row for row in connection.execute(text("SELECT draft_id,version,invocation_id,request_id,correlation_id,tenant_id FROM governed_llm_drafts WHERE tenant_id=:tenant"),{"tenant":tenant_id}).mappings().all()}
        invocations=set(connection.execute(text("SELECT invocation_id FROM llm_invocations WHERE tenant_id=:tenant"),{"tenant":tenant_id}).scalars().all())
        requests=set(connection.execute(text("SELECT request_id FROM llm_invocation_contexts WHERE tenant_id=:tenant"),{"tenant":tenant_id}).scalars().all())
        return drafts,invocations,requests

    @staticmethod
    def _trust_reference_failures(kind,value,context):
        drafts,invocations,requests=context;reasons=[];draft=drafts.get(value.get("draft_id"))
        if kind in {"draft_lifecycle","human_review"}:
            if draft is None or draft["version"]!=value.get("draft_version"):reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
        if kind=="human_review":
            if value.get("invocation_id") not in invocations or value.get("request_id") not in requests:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            elif draft and (value.get("invocation_id")!=draft["invocation_id"] or value.get("request_id")!=draft["request_id"] or value.get("correlation_id")!=draft["correlation_id"]):reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
        if kind=="review_security":
            if value.get("draft_id") and (draft is None or draft["version"]!=value.get("draft_version")):reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            if value.get("invocation_id") and value.get("invocation_id") not in invocations:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            if value.get("request_id") and value.get("request_id") not in requests:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            if draft and value.get("invocation_id") and value.get("invocation_id")!=draft["invocation_id"]:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            if draft and value.get("request_id") and value.get("request_id")!=draft["request_id"]:reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
        return reasons

    def replay_evidence_package(self, package_id: str) -> StreamReplayReport:
        with self._engine.connect() as connection:
            catalog = connection.execute(text("""
                SELECT package_payload, association_payload FROM evidence_package_catalog
                WHERE package_id=:package_id
            """), {"package_id": package_id}).mappings().first()
            versions = connection.execute(text("""
                SELECT id, package_version, integrity_hash FROM evidence_package_versions
                WHERE package_id=:package_id ORDER BY id
            """), {"package_id": package_id}).mappings().all()
            ledger_hashes = set(connection.execute(text(
                "SELECT event_hash FROM canonical_ledger_events"
            )).scalars().all())
        failures: list[ReplayFailure] = []
        verified: list[str] = []
        if catalog is None:
            failures.append(ReplayFailure(package_id, None, ("STREAM_COMPLETENESS_FAILURE",)))
            return self._report(f"evidence_package_versions:{package_id}", verified, failures)
        package = dict(catalog["package_payload"])
        association = dict(catalog["association_payload"])
        unsigned = {
            "package_id": package.get("package_id"), "package_version": package.get("package_version"),
            "verification_status": package.get("verification_status"),
            "publication_identities": package.get("publication_identities"),
            "relationships": package.get("claim_evidence_relationships"),
            "provenance_references": package.get("provenance_references"),
            "ledger_references": package.get("ledger_references"),
            "verification_references": package.get("verification_references"),
            "policy_version": package.get("policy_version"), "pipeline_version": package.get("pipeline_version"),
            "created_at": package.get("created_at"), "expires_at": package.get("expires_at"),
            "revalidation_required_at": package.get("revalidation_required_at"),
        }
        expected_hash = _hash(unsigned, ensure_ascii=False)
        seen_versions = set()
        if not versions:
            failures.append(ReplayFailure(package_id, None, ("STREAM_COMPLETENESS_FAILURE",)))
        for index, version in enumerate(versions, 1):
            event_id = f"{package_id}:{version['package_version']}"
            reasons = []
            if version["package_version"] in seen_versions:
                reasons.append("DUPLICATE_EVENT")
            seen_versions.add(version["package_version"])
            if version["integrity_hash"] != expected_hash or package.get("integrity_hash") != expected_hash:
                reasons.append("MODIFIED_PAYLOAD")
            if version["package_version"] != package.get("package_version"):
                reasons.append("BROKEN_VERSION_CHAIN")
            self._record(event_id, index, reasons, verified, failures)
        association_hashes = association.get("ledger_event_hashes") or []
        if (association.get("package_id") != package_id
                or association_hashes != (package.get("ledger_references") or [])
                or not set(association_hashes).issubset(ledger_hashes)
                or not package.get("provenance_references")):
            failures.append(ReplayFailure(
                package_id, None, ("INCONSISTENT_PROVENANCE_REFERENCES",),
            ))
        return self._report(f"evidence_package_versions:{package_id}", verified, failures)

    def replay_persisted_gateway_input(self,identifier,*,tenant_id=None):
        from jmoraIs.infrastructure.persisted_gateway_input import _decode, PostgreSQLPersistedGatewayInputRepository
        from jmoraIs.gateway_input import persisted_gateway_input_integrity_hash
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT *,to_jsonb(source) AS persisted_row FROM persisted_gateway_inputs source WHERE persisted_gateway_input_id=:id"),{"id":identifier}).mappings().first()
            links=connection.execute(text("SELECT invocation_id,tenant_id,upstream_artifact_type,upstream_artifact_id,upstream_artifact_version FROM llm_invocations WHERE persisted_gateway_input_id=:id"),{"id":identifier}).mappings().all()
            effective_tenant=tenant_id or (row["tenant_id"] if row else None)
            checkpoint=self._checkpoint(connection,"persisted_gateway_inputs",
                self._checkpoint_id(effective_tenant,identifier)) if effective_tenant else None
        failures=[];verified=[]
        if row is None:
            report=self._report(f"persisted_gateway_inputs:{effective_tenant}:{identifier}",(),(ReplayFailure(identifier,None,("STREAM_COMPLETENESS_FAILURE",)),))
            return self._with_checkpoint_details(report,checkpoint,None)
        try:
            record=_decode(row["payload"]);reference=record.upstream_artifact_reference
            reasons=[]
            if tenant_id is not None and row["tenant_id"]!=tenant_id:reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            if record.persisted_gateway_input_id!=identifier or record.integrity_hash!=persisted_gateway_input_integrity_hash(record) or row["record_integrity_hash"]!=record.integrity_hash:reasons.append("MODIFIED_PAYLOAD")
            columns=(row["tenant_id"],row["artifact_type"],row["artifact_id"],row["artifact_version"],row["dto_hash"],row["attestation"])
            expected=(reference.tenant_id,reference.artifact_type,reference.artifact_id,reference.artifact_version,record.dto_hash,record.attestation)
            if columns!=expected:reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            PostgreSQLPersistedGatewayInputRepository._checked(row)
            defense=record.audit_defense_reference
            if defense is not None:
                with self._engine.connect() as connection:
                    owner=connection.execute(text("""SELECT * FROM audit_defense_persisted_references
                      WHERE tenant_id=:tenant AND reference_id=:id"""),
                      {"tenant":defense.tenant_id,"id":defense.reference_id}).mappings().one_or_none()
                expected_owner=(defense.stream_id,defense.version,defense.package_id,defense.policy_version,defense.integrity_hash,defense.issued_at)
                if owner is None or tuple(owner[k] for k in ("stream_id","package_version","package_id","policy_version","integrity_hash","issued_at"))!=expected_owner:
                    reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            if any((x["tenant_id"],x["upstream_artifact_type"],x["upstream_artifact_id"],x["upstream_artifact_version"])!=(reference.tenant_id,reference.artifact_type,reference.artifact_id,reference.artifact_version) for x in links):reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            self._record(identifier,1,reasons,verified,failures)
        except Exception:failures.append(ReplayFailure(identifier,1,("MODIFIED_PAYLOAD",)))
        self._verify_checkpoint(({"stream_position":1,"event_hash":row["record_integrity_hash"]},),checkpoint,failures)
        report=self._report(f"persisted_gateway_inputs:{row['tenant_id']}:{identifier}",verified,failures)
        return self._with_checkpoint_details(report,checkpoint,row["record_integrity_hash"])

    @staticmethod
    def _with_checkpoint_details(report,checkpoint,observed_hash):
        return StreamReplayReport(
            report.stream,report.verified_events,report.failed_events,report.broken_chains,
            report.tampered_events,report.completeness_verified,report.integrity_status,
            checkpoint_found=checkpoint is not None,
            expected_records=checkpoint["stream_position"] if checkpoint else None,
            observed_records=1 if observed_hash is not None else 0,
            expected_head_hash=checkpoint["head_hash"] if checkpoint else None,
            observed_head_hash=observed_hash,
        )

    def replay_stream(self, table: str, stream_id: str) -> StreamReplayReport:
        definition = next((item for item in _EVENT_STREAMS if item.table == table), None)
        if definition is None:
            raise ValueError("unsupported append-only stream")
        with self._engine.connect() as connection:
            rows = connection.execute(text(f"""
                SELECT event_id, {definition.owner} AS owner_id, stream_position,
                       previous_event_hash, event_hash, occurred_at, payload
                  FROM {definition.table}
                 WHERE {definition.owner} = :stream_id
                 ORDER BY stream_position, sequence_id
            """), {"stream_id": stream_id}).mappings().all()
            context = self._reference_context(connection, definition, stream_id)
            checkpoint = self._checkpoint(connection, definition.table, stream_id)
        return self._verify_event_rows(definition, stream_id, rows, context, checkpoint)

    def replay_governed_evidence(self, package_id: str) -> StreamReplayReport:
        with self._engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT governed_evidence_id AS event_id, evidence_package_id AS owner_id,
                       stream_version AS stream_position, NULL::text AS previous_event_hash,
                       integrity_hash AS event_hash, issued_at AS occurred_at, payload
                  FROM governed_evidence_versions
                 WHERE evidence_package_id = :package_id
                 ORDER BY stream_version, sequence_id
            """), {"package_id": package_id}).mappings().all()
            ledger_hashes = set(connection.execute(text(
                "SELECT event_hash FROM canonical_ledger_events"
            )).scalars().all())
            checkpoint = self._checkpoint(connection, "governed_evidence_versions", package_id)
        verified, failures, seen = [], [], set()
        previous_time = None
        expected_position = 1
        for row in rows:
            reasons: list[str] = []
            payload = dict(row["payload"])
            event_id = str(row["event_id"])
            position = row["stream_position"]
            if position != expected_position:
                reasons.append("BROKEN_VERSION_CHAIN")
            expected_position += 1
            if event_id in seen:
                reasons.append("DUPLICATE_EVENT")
            seen.add(event_id)
            if payload.get("governed_evidence_id") != event_id or payload.get("evidence_package_id") != package_id:
                reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            supplied = payload.pop("integrity_hash", row["event_hash"])
            if supplied != row["event_hash"] or _hash(payload, ensure_ascii=False) != row["event_hash"]:
                reasons.append("MODIFIED_PAYLOAD")
            timestamp = self._timestamp(payload.get("issued_at") or row["occurred_at"])
            if previous_time and timestamp < previous_time:
                reasons.append("INVALID_TIMESTAMP_ORDER")
            previous_time = timestamp
            provenance = payload.get("provenance_references") or []
            ledger = payload.get("ledger_references") or []
            if not provenance or not ledger or not set(ledger).issubset(ledger_hashes):
                reasons.append("INCONSISTENT_PROVENANCE_REFERENCES")
            self._record(event_id, position, reasons, verified, failures)
        self._verify_checkpoint(rows, checkpoint, failures)
        return self._report(f"governed_evidence_versions:{package_id}", verified, failures)

    def _verify_event_rows(self, definition, stream_id, rows, context, checkpoint):
        verified: list[str] = []
        failures: list[ReplayFailure] = []
        seen_ids: set[str] = set()
        seen_hashes: set[str] = set()
        seen_payload_ids: set[str] = set()
        seen_payload_hashes: set[str] = set()
        expected_previous = None
        previous_time = None
        expected_position = 1
        for row in rows:
            payload = dict(row["payload"])
            event_id = str(row["event_id"])
            position = row["stream_position"]
            reasons: list[str] = []
            if position != expected_position:
                reasons.append("BROKEN_STREAM_POSITION")
            expected_position += 1
            if event_id in seen_ids or row["event_hash"] in seen_hashes:
                reasons.append("DUPLICATE_EVENT")
            seen_ids.add(event_id)
            seen_hashes.add(row["event_hash"])
            payload_id = str(payload.get("event_id"))
            payload_hash = str(payload.get("event_hash"))
            if payload_id in seen_payload_ids or payload_hash in seen_payload_hashes:
                reasons.append("DUPLICATE_EVENT")
            seen_payload_ids.add(payload_id)
            seen_payload_hashes.add(payload_hash)
            if payload.get("event_id") != event_id or payload.get(definition.owner) != stream_id:
                reasons.append("ROW_PAYLOAD_IDENTITY_MISMATCH")
            payload_previous = payload.get("previous_event_hash")
            if row["previous_event_hash"] != expected_previous or payload_previous != expected_previous:
                reasons.append("BROKEN_PREVIOUS_HASH")
            supplied_payload_hash = payload.pop("event_hash", row["event_hash"])
            canonical = self._canonical_hash_payload(definition.kind, payload)
            if supplied_payload_hash != row["event_hash"] or _hash(
                canonical, ensure_ascii=definition.kind != "scientific"
            ) != row["event_hash"]:
                reasons.append("MODIFIED_PAYLOAD")
            timestamp = self._timestamp(payload.get("occurred_at") or row["occurred_at"])
            if previous_time and timestamp < previous_time:
                reasons.append("INVALID_TIMESTAMP_ORDER")
            previous_time = timestamp
            reasons.extend(self._reference_failures(definition.kind, payload, context))
            self._record(event_id, position, reasons, verified, failures)
            expected_previous = row["event_hash"]
        self._verify_checkpoint(rows, checkpoint, failures)
        return self._report(f"{definition.table}:{stream_id}", verified, failures)

    @staticmethod
    def _checkpoint(connection, namespace, stream_id):
        return connection.execute(text("""
            SELECT stream_position, head_hash
              FROM cryptographic_stream_checkpoints
             WHERE stream_namespace=:namespace AND stream_id=:stream_id
             ORDER BY stream_position DESC LIMIT 1
        """), {"namespace": namespace, "stream_id": stream_id}).mappings().first()

    @staticmethod
    def _verify_checkpoint(rows, checkpoint, failures):
        position = rows[-1]["stream_position"] if rows else 0
        head_hash = rows[-1]["event_hash"] if rows else None
        if checkpoint is None or checkpoint["stream_position"] != position or checkpoint["head_hash"] != head_hash:
            failures.append(ReplayFailure(
                "STREAM_COMPLETENESS", position, ("STREAM_COMPLETENESS_FAILURE",),
            ))

    @staticmethod
    def _canonical_hash_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "audit":
            return {
                "event_id": payload.get("event_id"), "case_id": payload.get("case_id"),
                "event_type": payload.get("event_type"), "occurred_at": payload.get("occurred_at"),
                "governed_evidence_ids": payload.get("governed_evidence_ids"),
                "recommendation_ids": payload.get("recommendation_ids"),
                "weighting": payload.get("weighting_decisions"),
                "conflicts": payload.get("conflict_decisions"),
                "confidence": payload.get("confidence_inputs"),
                "review_from": payload.get("review_from"), "review_to": payload.get("review_to"),
                "reviewer_id": payload.get("reviewer_id"), "actor_role": payload.get("actor_role"),
                "policy_version": payload.get("policy_version"), "justification": payload.get("justification"),
                "previous_event_hash": payload.get("previous_event_hash"),
            }
        return payload

    @staticmethod
    def _reference_context(connection, definition, stream_id):
        if definition.kind == "scientific":
            claims = set(connection.execute(text(
                "SELECT claim_id FROM canonical_ledger_claims WHERE claim_id=:id"
            ), {"id": stream_id}).scalars().all())
            supports = set(connection.execute(text(
                "SELECT support_id FROM canonical_ledger_supports WHERE claim_id=:id"
            ), {"id": stream_id}).scalars().all())
            return claims, supports
        if definition.kind == "audit":
            governed = set(connection.execute(text(
                "SELECT governed_evidence_id FROM governed_evidence_versions"
            )).scalars().all())
            return governed
        return None

    @staticmethod
    def _reference_failures(kind, payload, context):
        failures = []
        if kind == "scientific":
            claims, supports = context
            if payload.get("claim_id") not in claims:
                failures.append("INCONSISTENT_PROVENANCE_REFERENCES")
            for key in ("support_id", "target_support_id", "replacement_support_id"):
                if payload.get(key) and payload[key] not in supports:
                    failures.append("INCONSISTENT_PROVENANCE_REFERENCES")
                    break
        elif kind == "audit" and not set(payload.get("governed_evidence_ids") or ()).issubset(context):
            failures.append("INCONSISTENT_PROVENANCE_REFERENCES")
        return failures

    @staticmethod
    def _timestamp(value):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _record(event_id, position, reasons, verified, failures):
        if reasons:
            failures.append(ReplayFailure(event_id, position, tuple(dict.fromkeys(reasons))))
        else:
            verified.append(event_id)

    @staticmethod
    def _report(stream, verified, failures):
        broken = tuple(
            failure.event_id for failure in failures
            if any("CHAIN" in reason or "POSITION" in reason or "PREVIOUS" in reason for reason in failure.reasons)
        )
        status = ReplayIntegrityStatus.TAMPERED if failures else ReplayIntegrityStatus.VALID
        completeness_verified = not any(
            "STREAM_COMPLETENESS_FAILURE" in failure.reasons for failure in failures
        )
        return StreamReplayReport(
            stream, tuple(verified), tuple(failures), broken,
            tuple(failure.event_id for failure in failures), completeness_verified, status,
        )
