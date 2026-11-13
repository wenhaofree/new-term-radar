# Deploy: daily cron + PostgreSQL

This repo is the **collector**. It still writes `state/` (SQLite + snapshots) for diffs and the 14-day review. When `DATABASE_URL` is set, each `daily` run also upserts product tables for a separate frontend.

## 1. Database

```bash
docker compose up -d
cp .env.example .env   # fill AISA_API_KEY, DATABASE_URL, optional webhooks
uv sync --extra pg --extra mail
```

Default URL: `postgresql://radar:radar@127.0.0.1:5432/radar`

Tables (created on first write):

| Table / view | Role |
|---|---|
| `reports` | One row per daily batch (status, cost, markdown/json, errors) |
| `keyword_opportunities` | Full keyword matrix (paid API) |
| `v_keyword_opportunities_free` | Free-tier columns only (`volume_band`, no exact volume / weak sites) |
| `discovered_leads` | Today’s new names + `format` for the free board |

`is_acted` on `keyword_opportunities` is an ops follow-up flag, not a subscription flag.

## 2. Preflight and alerts

Before paid work, `daily` pings AIsa (and GoAnyAPI / TrustMRR when configured). On failure it exits `1` and posts to `RADAR_WEBHOOK_URL`.

| Variable | Meaning |
|---|---|
| `RADAR_WEBHOOK_URL` | Feishu / DingTalk / Telegram / generic webhook |
| `RADAR_WEBHOOK_TYPE` | `feishu` (default when URL matches), `dingtalk`, `telegram`, `generic` |

Emergency: `--skip-preflight` (not for production cron).

## 3. Cron with flock

```bash
chmod +x scripts/run-daily.sh
mkdir -p logs
```

Crontab example (server local time; adjust TZ):

```cron
0 8 * * * cd /opt/new-term-radar && ./scripts/run-daily.sh >> logs/daily.log 2>&1
```

`flock -n /tmp/radar-daily.lock` prevents overlapping runs (no double API spend, no concurrent upserts). If the lock is held, the script exits `0` and logs a skip.

Override paths with `RADAR_LOCK` / `RADAR_OUT`.

## 4. Exit codes

| Code | Meaning |
|---|---|
| 0 | `status=success` and Postgres write ok (or DB unset) |
| 1 | preflight failed, run `partial`/`failed`, or Postgres write failed |

## 5. Frontend contract (read-only)

- Free: `discovered_leads` + `v_keyword_opportunities_free`
- Paid: `keyword_opportunities` (+ optional `reports.report_md` / `report_json`)
- Same-day re-runs upsert on `(discovered_date, keyword, kind)` and `(discovered_date, term)`
