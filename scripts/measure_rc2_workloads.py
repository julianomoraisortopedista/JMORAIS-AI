#!/usr/bin/env python3
"""Measure canonical workload scenario wall time without modifying production code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from evaluation.performance.rc2_benchmark import percentiles


WORKLOADS = {
    "B_authentication_session_jti": "tests/test_session_security.py::test_active_session_and_reusable_jti_are_accepted",
    "C_patient_context_ingestion": "tests/test_patient_context_application.py::test_retrieve_and_version_history_are_append_only",
    "D_clinical_state": "tests/test_clinical_state.py::test_current_state_is_immutable_reference_based_and_preserves_epistemic_status",
    "E_terminology": "tests/test_terminology.py::test_canonical_and_synonym_mapping_are_deterministic_and_immutable",
    "F_evidence_package": "tests/test_evidence_package_boundary.py::test_nonexistent_package_is_rejected",
    "G_clinical_appraisal": "tests/test_clinical_appraisal_persistence.py::test_canonical_appraisal_is_immutable_versioned_and_traceable",
    "H_governed_evidence": "tests/test_governed_clinical_integration.py::test_valid_governed_evidence_is_accepted_and_ranked",
    "I_reasoning_input": "tests/test_reasoning_input.py::test_contract_is_immutable_reference_only_and_contains_versions",
    "J_guideline_engine": "tests/test_guideline_engine.py::test_valid_guideline_is_applicable_explainable_and_not_actionable",
    "K_orthopedic_intelligence": "tests/test_orthopedic_intelligence.py::test_mechanical_stability_alignment_function_and_history_are_structured_references",
    "L_medical_document": "tests/test_medical_document_engine.py::test_only_canonical_reasoning_input_is_accepted",
    "M_audit_defense": "tests/test_audit_defense.py::test_source_bound_defense_is_immutable_traceable_and_non_actionable",
    "N_persisted_gateway_input": "tests/test_persisted_gateway_input.py::test_owner_issued_input_is_atomic_immutable_and_persisted_on_invocation",
    "O_llm_gateway_mock": "tests/test_llm_gateway.py::test_mock_provider_gateway_cost_tokens_audit_and_no_external_actionability",
    "P_governed_llm_draft": "tests/test_governed_llm_draft.py::test_eligible_gateway_output_issues_immutable_reviewable_draft",
    "Q_human_review": "tests/test_llm_human_review.py::test_authorized_human_approval_is_immutable_append_only_and_not_actionable",
    "R_complete_case_1_14": "tests/test_complete_case_stage1_7_postgresql.py::test_complete_case_1_to_14_persists_restarts_and_traces_exactly",
    "S_cryptographic_replay": "tests/test_cryptographic_ledger_replay.py::test_full_replay_from_genesis_is_valid_and_structured",
}


def main() -> int:
    samples = int(os.getenv("RC2_SCENARIO_SAMPLES", "3")); results = {}
    selected = {item.strip() for item in os.getenv("RC2_WORKLOAD_FILTER", "").split(",") if item.strip()}
    workloads = {name: node for name, node in WORKLOADS.items() if not selected or name in selected}
    unknown = selected.difference(workloads)
    if unknown:
        raise ValueError(f"unknown RC2 workload(s): {', '.join(sorted(unknown))}")
    for name, node in workloads.items():
        values = []
        for _ in range(samples):
            started = time.perf_counter()
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", node],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
            elapsed = (time.perf_counter() - started) * 1000
            if completed.returncode:
                raise RuntimeError(f"{name} failed closed:\n{completed.stdout[-4000:]}")
            values.append(elapsed)
        results[name] = {"node_id": node, "samples": samples,
            "scenario_wall_ms": percentiles(values), "success_rate": 1.0,
            "measurement_scope": "pytest process + fixture + canonical operation + assertions"}
    output = Path(os.getenv("RC2_SCENARIO_REPORT", "/tmp/rc2-scenarios.json"))
    output.write_text(json.dumps({"schema_version": 1, "workloads": results}, indent=2,
                                 sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
