"""Benchmark index data for portfolio comparison overlays.

Fetches TA-125 and TA-35 historical closing prices from Yahoo Finance and
caches them in the settings table to avoid a live HTTP call on every page load.
Cache TTL: 24 hours.

The returned series are aligned to the portfolio snapshot dates and normalised
so that the first data-point equals the portfolio value on that same date.
This lets both series share the same Y-axis and makes the comparison
meaningful: "what would my portfolio be worth today if I had invested in the
index instead?"
"""

from datetime import datetime, timedelta

_SYMBOLS = {
    'ta125':     '^TA125.TA',
    'ta35':      'TA35.TA',
    'sp500':     '^GSPC',
    'ndq':       '^NDX',      # Nasdaq-100 (what QQQ tracks)
    'nikkei':    '^N225',
    'kospi200':  '^KS200',
    'eurostoxx': '^STOXX50E',  # EURO STOXX 50
}

_CACHE_TTL_HOURS = 24
_SETTINGS_KEY = 'benchmark_cache_v4'  # bumped when the index set/symbols change


def _load_cache():
    # Benchmark indices are market facts — shared across all portfolios.
    from app.settings import get_shared_setting
    return get_shared_setting(_SETTINGS_KEY) or {}


def _save_cache(data):
    from app.settings import set_shared_setting
    set_shared_setting(_SETTINGS_KEY, data)


def _fetch_history(symbol, start_date, end_date):
    """Fetch daily closing prices from yfinance. Returns {date_str: close} dict."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start_date, end=end_date, interval='1d', auto_adjust=True)
        if hist.empty:
            return {}
        result = {}
        for ts, row in hist.iterrows():
            date_str = ts.strftime('%Y-%m-%d')
            close = row.get('Close')
            if close is not None and close == close:  # NaN check
                result[date_str] = round(float(close), 4)
        return result
    except Exception:
        return {}


def get_benchmark_data(snapshot_dates):
    """Return benchmark series aligned and normalised to the portfolio snapshots.

    Args:
        snapshot_dates: list of ISO date strings from the portfolio snapshots,
                        sorted ascending.

    Returns:
        {
          'ta125': [float|None, ...],   # one value per snapshot_date, or None
          'ta35':  [float|None, ...],
        }
        Values are normalised so the first non-None value equals the portfolio
        market value on that date — but since we don't have the portfolio value
        here, we return the *raw* scaled series (normalised to 1.0 at first
        available date).  The caller scales to the portfolio start value in JS.

    Returns empty series on yfinance failure.
    """
    if not snapshot_dates:
        return {k: [] for k in _SYMBOLS}

    start = snapshot_dates[0]
    # Fetch a day beyond the last snapshot so end_date is inclusive
    try:
        end_dt = datetime.strptime(snapshot_dates[-1], '%Y-%m-%d') + timedelta(days=1)
        end = end_dt.strftime('%Y-%m-%d')
    except ValueError:
        end = snapshot_dates[-1]

    now_str = datetime.utcnow().isoformat()
    cache = _load_cache()
    cache_valid = False

    if (cache.get('start') == start and cache.get('end') == end
            and all(k in cache for k in _SYMBOLS)):  # refetch if a new index was added
        fetched_at = cache.get('fetched_at', '')
        if fetched_at:
            try:
                age_h = (datetime.utcnow() - datetime.fromisoformat(fetched_at)).total_seconds() / 3600
                cache_valid = age_h < _CACHE_TTL_HOURS
            except (ValueError, TypeError):
                pass

    if not cache_valid:
        new_cache = {'start': start, 'end': end, 'fetched_at': now_str}
        for key, symbol in _SYMBOLS.items():
            new_cache[key] = _fetch_history(symbol, start, end)
        _save_cache(new_cache)
        cache = new_cache

    result = {}
    for key in _SYMBOLS:
        prices = cache.get(key) or {}
        # Align: for each snapshot date, find the closest available price
        # (markets may be closed on days the portfolio has a snapshot, e.g. holidays)
        series = []
        sorted_dates = sorted(prices.keys())
        for snap_date in snapshot_dates:
            if snap_date in prices:
                series.append(prices[snap_date])
            else:
                # Find the most recent available price before this date
                prev = [d for d in sorted_dates if d <= snap_date]
                series.append(prices[prev[-1]] if prev else None)
        result[key] = series

    return result
