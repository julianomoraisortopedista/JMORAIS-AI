from __future__ import annotations

import ast
from pathlib import Path


ROOTS = (Path("jmoraIs"), Path("evaluation"), Path("tests"), Path("scripts"))
failures = []
for root in ROOTS:
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path}: syntax error: {exc}")
        for number, line in enumerate(source.splitlines(), 1):
            if line.rstrip() != line:
                failures.append(f"{path}:{number}: trailing whitespace")
            if "\t" in line:
                failures.append(f"{path}:{number}: tab indentation")
if failures:
    raise SystemExit("\n".join(failures))
print("source hygiene: PASS")
