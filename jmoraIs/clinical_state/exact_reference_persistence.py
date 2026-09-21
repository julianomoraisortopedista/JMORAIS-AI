from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from jmoraIs.tenancy.context import current_tenant_context

from .domain import PatientClinicalState
from .exact_reference import (
    ClinicalStateReferenceRejected, ClinicalStateTimelineReferenceRejected,
    LegacyMissingClinicalStateReference, PersistedClinicalStateReference,
    PersistedClinicalStateTimelineReference, reference_integrity, state_integrity,
    state_provenance_reference, timeline_integrity, validate_reference_integrity,
    validate_timeline_integrity,
)
from .persistence import ClinicalStateJsonCodec


class PostgreSQLClinicalStateExactReferenceRepository:
    """Clinical State owner-side exact state and exact timeline boundary."""

    def __init__(self, engine, codec=None, *, clock=None):
        if engine.dialect.name != "postgresql":
            raise ValueError("Clinical State exact references require PostgreSQL")
        self._engine = engine
        self._codec = codec or ClinicalStateJsonCodec()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def reference_for(self, state: PatientClinicalState):
        if not isinstance(state, PatientClinicalState):
            raise ClinicalStateReferenceRejected("typed PatientClinicalState is required")
        tenant = current_tenant_context()
        row = self._state_row(state.state_id)
        if row is None:
            raise LegacyMissingClinicalStateReference("LEGACY_MISSING_CLINICAL_STATE_REFERENCE")
        canonical = self._decode_state_row(row)
        if canonical != state:
            raise ClinicalStateReferenceRejected("Clinical State does not match exact canonical persistence")
        self._validate_state_columns(canonical, row, tenant.tenant_id)
        predecessor_id = None
        predecessor_version = None
        if state.state_version > 1:
            predecessor = self._reference_row_for_state(state.previous_state_id, state.state_version - 1)
            if predecessor is None:
                raise LegacyMissingClinicalStateReference("LEGACY_MISSING_CLINICAL_STATE_REFERENCE")
            predecessor_id = predecessor["reference_id"]
            predecessor_version = predecessor["state_version"]
        issued = self._clock()
        unsigned = PersistedClinicalStateReference(
            "csr_" + uuid4().hex, state.state_id, state.state_version,
            state.pseudonymous_patient_id, tenant.tenant_id, tenant.policy_version,
            predecessor_id, predecessor_version, state_provenance_reference(state),
            state_integrity(self._codec, state), "0" * 64, issued)
        reference = replace(unsigned, integrity_hash=reference_integrity(unsigned))
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO clinical_state_persisted_references
              (reference_id,state_id,state_version,pseudonymous_patient_id,tenant_id,policy_version,
               predecessor_reference_id,predecessor_state_version,provenance_reference,
               state_integrity_hash,integrity_hash,issued_at)
              VALUES(:reference,:state,:version,:patient,:tenant,:policy,:predecessor,:predecessor_version,
               :provenance,:state_hash,:integrity,:issued)"""),
              {"reference": reference.reference_id, "state": reference.state_id,
               "version": reference.state_version, "patient": reference.pseudonymous_patient_id,
               "tenant": reference.tenant_id, "policy": reference.policy_version,
               "predecessor": reference.predecessor_reference_id,
               "predecessor_version": reference.predecessor_state_version,
               "provenance": reference.provenance_reference,
               "state_hash": reference.state_integrity_hash,
               "integrity": reference.integrity_hash, "issued": reference.issued_at})
        return reference

    def get_exact(self, reference: PersistedClinicalStateReference):
        if not validate_reference_integrity(reference):
            raise ClinicalStateReferenceRejected("authentic owner-issued Clinical State reference is required")
        tenant = current_tenant_context()
        if reference.tenant_id != tenant.tenant_id or reference.policy_version != tenant.policy_version:
            raise ClinicalStateReferenceRejected("Clinical State reference tenant or policy mismatch")
        persisted = self._reference_row(reference.reference_id)
        if persisted is None or self._decode_reference(persisted) != reference:
            raise ClinicalStateReferenceRejected("persisted Clinical State reference is unavailable or inconsistent")
        row = self._state_row(reference.state_id)
        if row is None:
            raise ClinicalStateReferenceRejected("exact referenced Clinical State is unavailable")
        state = self._decode_state_row(row)
        self._validate_state_columns(state, row, tenant.tenant_id)
        if (state.state_version != reference.state_version or
            state.pseudonymous_patient_id != reference.pseudonymous_patient_id or
            state_integrity(self._codec, state) != reference.state_integrity_hash or
            state_provenance_reference(state) != reference.provenance_reference):
            raise ClinicalStateReferenceRejected("Clinical State payload/reference integrity mismatch")
        self._validate_predecessor(reference, state)
        return state

    def timeline_reference_for(self, exact_state_references):
        references = tuple(exact_state_references)
        self._validate_timeline_members(references)
        for reference in references:
            self.get_exact(reference)
        tenant = current_tenant_context(); issued = self._clock()
        unsigned = PersistedClinicalStateTimelineReference(
            "cst_" + uuid4().hex, references[0].pseudonymous_patient_id,
            tenant.tenant_id, tenant.policy_version, references, "0" * 64, issued)
        timeline = replace(unsigned, integrity_hash=timeline_integrity(unsigned))
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO clinical_state_timeline_references
              (timeline_reference_id,pseudonymous_patient_id,tenant_id,policy_version,
               member_count,integrity_hash,issued_at)
              VALUES(:id,:patient,:tenant,:policy,:count,:integrity,:issued)"""),
              {"id": timeline.timeline_reference_id, "patient": timeline.pseudonymous_patient_id,
               "tenant": timeline.tenant_id, "policy": timeline.policy_version,
               "count": len(references), "integrity": timeline.integrity_hash,
               "issued": timeline.issued_at})
            for position, reference in enumerate(references, 1):
                connection.execute(text("""INSERT INTO clinical_state_timeline_reference_members
                  (timeline_reference_id,position,state_reference_id,tenant_id)
                  VALUES(:timeline,:position,:reference,:tenant)"""),
                  {"timeline": timeline.timeline_reference_id, "position": position,
                   "reference": reference.reference_id, "tenant": timeline.tenant_id})
        return timeline

    def get_timeline_exact(self, reference: PersistedClinicalStateTimelineReference):
        if not validate_timeline_integrity(reference):
            raise ClinicalStateTimelineReferenceRejected("authentic owner-issued timeline reference is required")
        tenant = current_tenant_context()
        if reference.tenant_id != tenant.tenant_id or reference.policy_version != tenant.policy_version:
            raise ClinicalStateTimelineReferenceRejected("timeline tenant or policy mismatch")
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM clinical_state_timeline_references WHERE timeline_reference_id=:id"),
                {"id": reference.timeline_reference_id}).mappings().first()
            member_ids = tuple(connection.execute(text("""SELECT state_reference_id FROM
              clinical_state_timeline_reference_members WHERE timeline_reference_id=:id ORDER BY position"""),
              {"id": reference.timeline_reference_id}).scalars())
        expected_ids = tuple(item.reference_id for item in reference.state_references)
        if row is None or member_ids != expected_ids or row["member_count"] != len(expected_ids):
            raise ClinicalStateTimelineReferenceRejected("persisted timeline membership mismatch")
        actual = (row["timeline_reference_id"], row["pseudonymous_patient_id"], row["tenant_id"],
                  row["policy_version"], row["integrity_hash"], row["issued_at"])
        expected = (reference.timeline_reference_id, reference.pseudonymous_patient_id,
                    reference.tenant_id, reference.policy_version, reference.integrity_hash,
                    reference.issued_at)
        if actual != expected:
            raise ClinicalStateTimelineReferenceRejected("persisted timeline metadata mismatch")
        self._validate_timeline_members(reference.state_references)
        return tuple(self.get_exact(item) for item in reference.state_references)

    def _validate_timeline_members(self, references):
        if not references or any(not validate_reference_integrity(item) for item in references):
            raise ClinicalStateTimelineReferenceRejected("valid exact state references are required")
        first = references[0]
        if first.state_version != 1 or first.predecessor_reference_id is not None:
            raise ClinicalStateTimelineReferenceRejected("timeline must begin with the genesis state")
        if len({item.reference_id for item in references}) != len(references):
            raise ClinicalStateTimelineReferenceRejected("timeline contains duplicate members")
        for position, item in enumerate(references, 1):
            if (item.state_version != position or item.pseudonymous_patient_id != first.pseudonymous_patient_id
                or item.tenant_id != first.tenant_id or item.policy_version != first.policy_version):
                raise ClinicalStateTimelineReferenceRejected("timeline identity, policy or ordering mismatch")
            if position > 1 and item.predecessor_reference_id != references[position - 2].reference_id:
                raise ClinicalStateTimelineReferenceRejected("timeline predecessor continuity is invalid")

    def _validate_predecessor(self, reference, state):
        if state.state_version == 1:
            if state.previous_state_id is not None or reference.predecessor_reference_id is not None:
                raise ClinicalStateReferenceRejected("Clinical State genesis linkage is invalid")
            return
        predecessor = self._reference_row(reference.predecessor_reference_id)
        if predecessor is None:
            raise ClinicalStateReferenceRejected("Clinical State predecessor reference is unavailable")
        prior = self._decode_reference(predecessor)
        if (prior.state_id != state.previous_state_id or prior.state_version != state.state_version - 1
            or prior.pseudonymous_patient_id != state.pseudonymous_patient_id
            or prior.tenant_id != reference.tenant_id or prior.policy_version != reference.policy_version):
            raise ClinicalStateReferenceRejected("Clinical State predecessor continuity is invalid")

    @staticmethod
    def _decode_reference(row):
        return PersistedClinicalStateReference(row["reference_id"], row["state_id"], row["state_version"],
            row["pseudonymous_patient_id"], row["tenant_id"], row["policy_version"],
            row["predecessor_reference_id"], row["predecessor_state_version"],
            row["provenance_reference"], row["state_integrity_hash"], row["integrity_hash"], row["issued_at"])

    def _state_row(self, state_id):
        with self._engine.connect() as connection:
            return connection.execute(text("SELECT * FROM patient_clinical_state_versions WHERE state_id=:id"),
                                      {"id": state_id}).mappings().first()

    def _reference_row(self, reference_id):
        with self._engine.connect() as connection:
            return connection.execute(text("SELECT * FROM clinical_state_persisted_references WHERE reference_id=:id"),
                                      {"id": reference_id}).mappings().first()

    def _reference_row_for_state(self, state_id, version):
        with self._engine.connect() as connection:
            return connection.execute(text("""SELECT * FROM clinical_state_persisted_references
              WHERE state_id=:state AND state_version=:version"""),
              {"state": state_id, "version": version}).mappings().first()

    def _decode_state_row(self, row):
        state = self._codec.decode(row["payload"])
        if not isinstance(state, PatientClinicalState):
            raise ClinicalStateReferenceRejected("persisted Clinical State payload is invalid")
        return state

    @staticmethod
    def _validate_state_columns(state, row, tenant_id):
        actual = (row["state_id"], row["state_version"], row["patient_id"], row["tenant_id"],
                  row["previous_state_id"], row["patient_context_id"], row["patient_context_version"])
        expected = (state.state_id, state.state_version, state.pseudonymous_patient_id, tenant_id,
                    state.previous_state_id, state.patient_context_id, state.patient_context_version)
        if actual != expected:
            raise ClinicalStateReferenceRejected("Clinical State relational/payload linkage mismatch")
