from .terminology_projection import GovernedDocumentTerminologyProjection

class PostgreSQLGovernedDocumentTerminologyAdapter:
    """Restart-safe projection over the canonical PostgreSQL terminology repository."""
    def __init__(self,repository):self._repository=repository;self._projection=GovernedDocumentTerminologyProjection()
    def get(self,concept_id):return self._projection.project(self._repository.latest(concept_id))
