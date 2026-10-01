from pathlib import Path
from scripts.scan_release_sensitive_data import PATTERNS, is_type_annotation


def test_python_annotation_is_not_a_secret_but_assigned_value_is_checked():
    annotation = 'access_token: ' + 'SmartValidatedToken'
    match = PATTERNS['token'].search(annotation)
    assert match and is_type_annotation(Path('domain.py'),annotation,match)
    # Synthetic marker for detector testing, not usable credential material.
    assigned = 'access_token = "' + 'x'*24 + '"'
    match = PATTERNS['token'].search(assigned)
    assert match and not is_type_annotation(Path('domain.py'),assigned,match)
    assert not is_type_annotation(Path('fixture.js'),annotation,PATTERNS['token'].search(annotation))
