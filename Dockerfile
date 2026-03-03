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

# --workers 1 is mandatory: TinyDB CachingMiddleware is not multiprocess-safe
# --timeout 120 accommodates slow yfinance API calls
CMD ["gunicorn", \
     "--bind", "0.0.0.0:2501", \
     "--workers", "1", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "server:app"]
