# new-term-radar collector image. Joins Docker network wenhao-services to reach wenhao-postgres.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# System deps for psycopg binary wheels are usually enough; keep image slim.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY radar ./radar
COPY config.example.json ./

# Install project + PostgreSQL + optional mail extras into /.venv (uv default under /app)
RUN uv sync --frozen --extra pg --extra mail

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/state /app/logs /app/data

# Cron overrides the command; default is one daily run then exit.
CMD ["python", "-m", "radar", "daily", "--revenue", "--out", "/app/data/report.md"]
