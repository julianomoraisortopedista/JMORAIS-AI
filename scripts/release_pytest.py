"""Run focused pytest with metadata-only evidence (no captured secret payloads)."""
import json
from pathlib import Path
import sys

import pytest


class Evidence:
    def __init__(self):
        self.passed = 0
        self.skipped = 0
        self.failure = None
        self.category = 'UNKNOWN'

    def pytest_runtest_logreport(self, report):
        if report.skipped:self.skipped += 1
        if report.when == 'call' and report.passed:self.passed += 1
        if report.failed and self.failure is None:
            self.failure = report.nodeid
            detail = str(report.longrepr).lower()
            for needle, category in (('missing_select', 'PERMISSION'), ('permission denied', 'PERMISSION'),
                                     ('tampered', 'CRYPTOGRAPHIC'), ('rls', 'RLS'), ('fixture', 'FIXTURE')):
                if needle in detail:
                    self.category = category
                    break


if __name__ == '__main__':
    output = Path(sys.argv[1])
    evidence = Evidence()
    result = pytest.main(['-xq', *sys.argv[2:]], plugins=[evidence])
    output.write_text(json.dumps(dict(exit_code=int(result), passed=evidence.passed,
        skipped=evidence.skipped, first_failure=evidence.failure, classification=evidence.category)))
    raise SystemExit(result)
