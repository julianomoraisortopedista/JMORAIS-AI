from sqlalchemy import text

from jmoraIs.clinical_state.persistence import ClinicalStateJsonCodec

from .clinical_state_projection import AuditClinicalStateProjectionService


class PostgreSQLGovernedAuditClinicalStateAdapter:
    """RLS-backed restart-safe projection over canonical Clinical State persistence."""

    def __init__(self, engine):
        self._engine = engine
        self._codec = ClinicalStateJsonCodec()
        self._projection = AuditClinicalStateProjectionService()

    def facts(self, state_reference_id):
        with self._engine.connect() as connection:
            payload = connection.execute(
                text("SELECT payload FROM patient_clinical_state_versions WHERE state_id=:id"),
                {"id": state_reference_id},
            ).scalar_one_or_none()
        return self._projection.project(self._codec.decode(payload)) if payload else ()
