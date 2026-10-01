#!/usr/bin/env python3
"""Fail closed on likely secrets, patient identifiers, dumps, or local paths."""
from __future__ import annotations
import ast, re, subprocess
from pathlib import Path

PATTERNS = {
 "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
 "token": re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*['\"]?[A-Za-z0-9+/_.-]{16,}"),
 "patient_identifier": re.compile(r"(?i)(?:patient[_-]?name|cpf)\s*[:=]\s*['\"][^'\"]+['\"]"),
 "raw_jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
 "production_dsn": re.compile(r"(?i)(?:postgres(?:ql)?|mysql|mongodb)://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+"),
 "local_path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
}
ALLOW = {"scripts/scan_release_sensitive_data.py", "jmoraIs/structured_logging.py"}
SYNTHETIC_VALUES = ("local_ci_only", "ci_test_only", "local_test_only", "replace_me")

def is_type_annotation(path, source, match):
    """A Python annotation without a value is not credential material."""
    if path.suffix != '.py': return False
    line = source.count('\n', 0, match.start()) + 1
    column = match.start() - (source.rfind('\n', 0, match.start()) + 1)
    try: tree = ast.parse(source)
    except SyntaxError: return False
    return any(isinstance(node, ast.AnnAssign) and node.value is None
               and node.lineno == line and node.col_offset == column
               for node in ast.walk(tree))


def main() -> int:
    names=subprocess.check_output(["git","ls-files","--cached","--others","--exclude-standard"],text=True).splitlines()
    findings=[]
    for name in names:
        path=Path(name)
        if name in ALLOW or not path.is_file() or path.suffix in {".dump",".sqlite",".db",".pyc"}: continue
        try: text=path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for kind,pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                if kind == "token" and is_type_annotation(path, text, match):
                    continue
                if any(value in match.group(0) for value in SYNTHETIC_VALUES):
                    continue
                findings.append((name,text.count("\n",0,match.start())+1,kind))
    for finding in findings: print("%s:%s: %s"%finding)
    print(f"sensitive-data scan: {'FAIL' if findings else 'PASS'} ({len(findings)} findings)")
    return 1 if findings else 0

if __name__=="__main__": raise SystemExit(main())
