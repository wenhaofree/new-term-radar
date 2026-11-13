#!/usr/bin/env bash
# Daily radar with flock so a slow run cannot overlap the next cron tick.
#
#   ./scripts/run-daily.sh
#   ./scripts/run-daily.sh --skip x,hf
#
# Crontab (Asia/Shanghai 08:00), from the deploy docs:
#   0 8 * * * cd /opt/new-term-radar && ./scripts/run-daily.sh >> logs/daily.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

LOCK="${RADAR_LOCK:-/tmp/radar-daily.lock}"
OUT="${RADAR_OUT:-report.md}"

run_radar() {
  uv run --env-file .env python -m radar daily --revenue --out "$OUT" "$@"
}

if ! command -v flock >/dev/null 2>&1; then
  echo "run-daily: flock not found; running without lock" >&2
  run_radar "$@"
  exit $?
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "run-daily: previous run still holding $LOCK; skipped" >&2
  exit 0
fi

run_radar "$@"
