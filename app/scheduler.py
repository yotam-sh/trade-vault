"""Scheduled daily-close snapshot job for manual / US portfolios.

A daily-file (IBI) portfolio records its history from imports. A manual / US
portfolio has no such feed, so without this job its value-over-time series only
grows when the user trades or refreshes. After the US regular close each weekday
this writes a regular-close snapshot for every manual / non-TASE portfolio
(daily-file portfolios are import-driven and skipped).

Runs inside the single gunicorn worker as an APScheduler background thread.
Disabled unless ``ENABLE_SCHEDULER`` is set, so dev / tests / a multi-worker
deploy don't double-run. Scaling past one worker needs a single-owner guard
(e.g. a file lock) before enabling this in more than one process.
"""

import os
import threading
import logging

log = logging.getLogger(__name__)

_scheduler = None
_started = False
_lock = threading.Lock()


def scheduler_enabled():
    return os.environ.get('ENABLE_SCHEDULER', '').lower() in ('1', 'true', 'yes', 'on')


def _run_daily_close():
    """Write today's regular-close snapshot for each manual / US portfolio."""
    try:
        from datetime import date
        from app.utils.trading_calendar import is_us_non_trading_day

        today = date.today().isoformat()
        if is_us_non_trading_day(today):
            return

        from app import portfolios
        from app.connection import using_portfolio
        from app.backfill import _portfolio_has_daily_file
        from app.manual_portfolio import refresh_prices_and_snapshot

        for entry in portfolios.list_portfolios():
            pid = entry['id']
            try:
                with using_portfolio(pid):
                    if _portfolio_has_daily_file():
                        continue  # daily-file (e.g. IBI) portfolios are import-driven
                    refresh_prices_and_snapshot(prefer_session='regular')
            except Exception:
                log.exception('daily-close snapshot failed for portfolio %s', pid)
    except Exception:
        # A registry/setup hiccup must never escape into the scheduler thread.
        log.exception('daily-close job failed')


def start_scheduler():
    """Start the background scheduler once (idempotent). No-op unless enabled."""
    global _scheduler, _started
    if not scheduler_enabled():
        return False
    with _lock:
        if _started:
            return False
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo('America/New_York')
            except Exception:
                tz = 'America/New_York'
            _scheduler = BackgroundScheduler(timezone=tz)
            # 16:15 ET, after the regular close, mon–fri (holidays skipped in the job).
            _scheduler.add_job(_run_daily_close, 'cron', day_of_week='mon-fri',
                               hour=16, minute=15, id='daily_close',
                               misfire_grace_time=3600, coalesce=True)
            _scheduler.start()
            _started = True
            log.info('daily-close scheduler started (16:15 America/New_York, mon-fri)')
            return True
        except Exception:
            log.exception('failed to start scheduler')
            return False


def spawn_startup_catchup():
    """Background gap-fill: rebuild any days missed while the container was down.

    No-op unless the scheduler is enabled (keeps dev / tests network-free).
    """
    if not scheduler_enabled():
        return
    from app.backfill import catch_up_all
    threading.Thread(target=catch_up_all, daemon=True, name='backfill-catchup').start()
