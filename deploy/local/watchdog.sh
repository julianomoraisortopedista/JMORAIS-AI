#!/bin/zsh
# Runs every 5 minutes (launchd): if Docker is running and http://127.0.0.1/ does not answer,
# repair the local platform. Never starts Docker by itself and never prints credentials.
ROOT="${0:A:h:h:h}"
LOG="$HOME/.local/share/jmorais-local-pilot/watchdog.log"
export PATH="/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin"
[ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 200000 ] && tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
[ -S "$HOME/.docker/run/docker.sock" ] || exit 0          # Docker Desktop not running: nothing to do
curl -s -m 8 -o /dev/null -f http://127.0.0.1/ && exit 0  # healthy
echo "$(date '+%Y-%m-%d %H:%M:%S') página sem resposta; reparando" >> "$LOG"
cd "$ROOT" && "$ROOT/.venv/bin/python" -m deploy.local.control repair >> "$LOG" 2>&1
