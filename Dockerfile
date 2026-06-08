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
COPY server.py  .
COPY main.py    .
COPY wsgi.py    .
COPY gunicorn.conf.py .

# Create runtime directories (will be bind-mounted in production)
RUN mkdir -p /app/db /app/data/daily_data

# Non-root user for security
RUN addgroup --system tradevault && \
    adduser --system --ingroup tradevault tradevault && \
    chown -R tradevault:tradevault /app
USER tradevault

EXPOSE 2501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:2501/health')"

# Use the wsgi entrypoint + gunicorn.conf.py so one-time startup (migrations,
# repair, rolling backup) runs in the preloaded master. The config pins
# workers=1/threads=1 (TinyDB CachingMiddleware is not multi-process/-thread safe)
# and timeout=120 for slow yfinance calls.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
