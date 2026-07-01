# syntax=docker/dockerfile:1
FROM python:3.12-slim

# LANG/LC_ALL are essential for Hebrew string handling in Pandas and openpyxl
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# Install dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/       ./app/
COPY templates/ ./templates/
COPY static/    ./static/
COPY asset/     ./asset/
COPY server.py  .
COPY wsgi.py    .
COPY gunicorn.conf.py .

# Non-root user with FIXED uid/gid (10001) so volume ownership is deterministic
# and can be reproduced from the host (see the chown one-liner in README/compose).
RUN addgroup --system --gid 10001 tradevault && \
    adduser --system --uid 10001 --ingroup tradevault tradevault

# Create runtime directories (volume/bind-mounted in production) and hand them to
# the runtime user. /data/db is the DB volume mountpoint (DB_PATH=/data/db/db.json)
# and /app/data holds Excel uploads — both MUST be writable by tradevault or
# first-run writes (portfolios.json registry, db.json) fail with EACCES. An empty
# named volume inherits the image path's ownership, so chowning here fixes fresh
# deploys; pre-existing volumes must be chowned on the host (one-off, below).
RUN mkdir -p /app/db /app/data/daily_data /data/db && \
    chown -R tradevault:tradevault /app /data
USER tradevault

EXPOSE 2501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:2501/health')"

# Use the wsgi entrypoint + gunicorn.conf.py so one-time startup (migrations,
# repair, rolling backup) runs in the preloaded master. The config pins
# workers=1/threads=1 (TinyDB CachingMiddleware is not multi-process/-thread safe)
# and timeout=120 for slow yfinance calls.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
