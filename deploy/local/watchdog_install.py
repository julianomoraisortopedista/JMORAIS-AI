"""Install or remove the macOS launchd agent that runs deploy/local/watchdog.sh every 5 minutes."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = "com.jmorais.pilot-watchdog"
ROOT = Path(__file__).resolve().parents[2]
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / ".local/share/jmorais-local-pilot/watchdog.log"


def install() -> int:
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    PLIST.write_bytes(plistlib.dumps({
        "Label": LABEL, "ProgramArguments": ["/bin/zsh", str(ROOT / "deploy/local/watchdog.sh")],
        "StartInterval": 300, "RunAtLoad": True, "ProcessType": "Background",
        "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG)}))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    result = subprocess.run(["launchctl", "bootstrap", domain, str(PLIST)], capture_output=True, text=True)
    print("PASS: watchdog installed (every 5 min)" if result.returncode == 0 else "NOT_READY: " + result.stderr.strip()[:200])
    return result.returncode


def uninstall() -> int:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST.unlink(missing_ok=True)
    print("PASS: watchdog removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(uninstall() if sys.argv[1:] == ["uninstall"] else install())
