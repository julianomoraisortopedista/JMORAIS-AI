from __future__ import annotations
from typing import Protocol
from .domain import FhirCodeDecision


class FhirTerminologyValidationPort(Protocol):
    def validate(self, system: str, code: str, display: str | None) -> FhirCodeDecision: ...


class FhirIdempotencyQueryPort(Protocol):
    def find(self, source_reference_id: str): ...
