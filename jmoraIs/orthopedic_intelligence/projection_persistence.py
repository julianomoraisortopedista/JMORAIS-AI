from sqlalchemy import text
from jmoraIs.clinical_state.persistence import ClinicalStateJsonCodec
from .projection import OrthopedicStateProjectionService

class PostgreSQLGovernedOrthopedicStateQueryAdapter:
    """Reconstructs from tenant-scoped RLS sources; contains no cache."""
    def __init__(self,engine,terminology_service,terminology_version):self._engine=engine;self._projection=OrthopedicStateProjectionService(terminology_service);self._version=terminology_version;self._codec=ClinicalStateJsonCodec()
    def get(self,state_reference_id):
        with self._engine.connect() as connection:payload=connection.execute(text("SELECT payload FROM patient_clinical_state_versions WHERE state_id=:id"),{"id":state_reference_id}).scalar_one_or_none()
        return self._projection.project(self._codec.decode(payload),self._version) if payload else None
