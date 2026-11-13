#!/usr/bin/env bash
# Daily radar via Docker Compose (joins wenhao-services → wenhao-postgres).
# Host flock prevents overlapping compose runs.
#
#   ./scripts/run-daily-docker.sh
#   ./scripts/run-daily-docker.sh --skip x,hf
#
# Crontab (Asia/Shanghai 08:00):
#   0 8 * * * cd /opt/new-term-radar && ./scripts/run-daily-docker.sh >> logs/daily.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs state data

LOCK="${RADAR_LOCK:-/tmp/radar-daily.lock}"
OUT="${RADAR_OUT:-/app/data/report.md}"
COMPOSE="${DOCKER_COMPOSE:-docker compose}"

run_radar() {
  $COMPOSE run --rm --no-deps radar \
    python -m radar daily --revenue --out "$OUT" "$@"
}

if ! command -v flock >/dev/null 2>&1; then
  echo "run-daily-docker: flock not found; running without lock" >&2
  run_radar "$@"
  exit $?
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "run-daily-docker: previous run still holding $LOCK; skipped" >&2
  exit 0
fi

run_radar "$@"
