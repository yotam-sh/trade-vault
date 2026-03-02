"""Manual yfinance symbol mapping and English name fetching.

Allows users to manually map TASE paper numbers to Yahoo Finance symbols,
then fetches English stock names from yfinance.
"""

from app.holdings import update_holding, get_holding_by_tase_id
from app.settings import get_setting, set_setting


def fetch_info_from_yfinance(yfinance_symbol):
    """Fetch stock information from Yahoo Finance.

    Args:
        yfinance_symbol: Yahoo Finance symbol (e.g., "GNRS.TA", "TEVA.TA")

    Returns:
        Dictionary with 'name' and 'symbol' keys, or None if fetch fails
        {
            'name': str,    # English name
            'symbol': str   # Ticker symbol
        }

    Example:
        >>> fetch_info_from_yfinance("GNRS.TA")
        {'name': 'Generation Capital Ltd', 'symbol': 'GNRS.TA'}
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(yfinance_symbol)
        info = ticker.info

        # Fetch name - try multiple fields in order of preference
        name = None
        for field in ['longName', 'shortName', 'displayName']:
            if field in info and info[field]:
                name = info[field]
                break

        # Fetch symbol
        symbol = info.get('symbol', yfinance_symbol)

        if name:
            return {
                'name': name,
                'symbol': symbol
            }

        return None
    except Exception:
        return None


def set_yfinance_mapping(tase_id, yfinance_symbol, update_info=True):
    """Map a TASE paper number to a Yahoo Finance symbol and fetch stock info.

    Args:
        tase_id: TASE security ID number (e.g., 1156926)
        yfinance_symbol: Yahoo Finance symbol (e.g., "GNRS.TA")
        update_info: If True, fetch and update name + ticker from yfinance

    Returns:
        Dictionary with results:
        {
            'success': bool,
            'holding_id': int or None,
            'name_en': str or None,
            'ticker': str or None,
            'error': str or None
        }

    Example:
        >>> result = set_yfinance_mapping(1156926, "GNRS.TA")
        >>> print(result['name_en'])
        'Generation Capital Ltd'
        >>> print(result['ticker'])
        'GNRS.TA'
    """
    result = {
        'success': False,
        'holding_id': None,
        'name_en': None,
        'ticker': None,
        'error': None
    }

    # Find holding by TASE ID
    holding = get_holding_by_tase_id(tase_id)
    if not holding:
        result['error'] = f"No holding found with TASE ID {tase_id}"
        return result

    result['holding_id'] = holding.doc_id

    # Store the yfinance symbol mapping
    yfinance_map = get_setting('yfinance_map', {})
    yfinance_map[str(tase_id)] = yfinance_symbol
    set_setting('yfinance_map', yfinance_map)

    # Optionally fetch stock info from yfinance
    if update_info:
        info = fetch_info_from_yfinance(yfinance_symbol)
        if info:
            # Update both name and ticker
            update_holding(holding.doc_id, name_en=info['name'], ticker=info['symbol'])
            result['name_en'] = info['name']
            result['ticker'] = info['symbol']
            result['success'] = True
        else:
            result['error'] = f"Could not fetch info from yfinance for symbol: {yfinance_symbol}"
            # Still consider it a partial success - mapping was saved
            result['success'] = True
    else:
        result['success'] = True

    return result


def get_yfinance_mapping(tase_id=None):
    """Get yfinance symbol mapping for a TASE ID, or all mappings.

    Args:
        tase_id: Optional TASE security ID. If None, returns all mappings.

    Returns:
        If tase_id provided: yfinance symbol string or None
        If tase_id is None: dictionary of all mappings {tase_id: yfinance_symbol}

    Example:
        >>> get_yfinance_mapping(1156926)
        'GNRS.TA'

        >>> get_yfinance_mapping()
        {'1156926': 'GNRS.TA', '1410631': 'TEVA.TA'}
    """
    yfinance_map = get_setting('yfinance_map', {})

    if tase_id is not None:
        return yfinance_map.get(str(tase_id))
    else:
        return yfinance_map


def refresh_info_from_mappings(tase_ids=None):
    """Refresh stock info (name + ticker) from existing yfinance mappings.

    Useful for re-fetching info if yfinance data was updated.

    Args:
        tase_ids: Optional list of TASE IDs to refresh. If None, refreshes all mapped holdings.

    Returns:
        Dictionary with results:
        {
            'success': int,  # Number of successfully refreshed holdings
            'failed': int,   # Number of failed fetches
            'errors': [str]  # List of error messages
        }

    Example:
        >>> results = refresh_info_from_mappings([1156926, 1410631])
        >>> print(f"Refreshed {results['success']} holdings")
        Refreshed 2 holdings
    """
    results = {
        'success': 0,
        'failed': 0,
        'errors': []
    }

    yfinance_map = get_setting('yfinance_map', {})

    # Filter mappings if specific tase_ids provided
    if tase_ids:
        mappings = {str(tid): yfinance_map[str(tid)] for tid in tase_ids if str(tid) in yfinance_map}
    else:
        mappings = yfinance_map

    for tase_id_str, yfinance_symbol in mappings.items():
        tase_id = int(tase_id_str)
        holding = get_holding_by_tase_id(tase_id)

        if not holding:
            results['errors'].append(f"TASE ID {tase_id}: Holding not found")
            results['failed'] += 1
            continue

        info = fetch_info_from_yfinance(yfinance_symbol)
        if info:
            update_holding(holding.doc_id, name_en=info['name'], ticker=info['symbol'])
            results['success'] += 1
        else:
            results['errors'].append(f"TASE ID {tase_id} ({yfinance_symbol}): Could not fetch info")
            results['failed'] += 1

    return results


def fetch_rich_info_from_yfinance(yfinance_symbol):
    """Fetch extended company info from Yahoo Finance for the position page.

    Tries ticker.fast_info first (more reliable endpoint) for market data,
    then ticker.info for company metadata. Logs errors to stderr.

    Returns dict with sector, industry, description, 52w range, market cap, etc.
    Returns None if no usable data could be fetched.
    """
    import sys
    try:
        import yfinance as yf
        from datetime import date
        ticker = yf.Ticker(yfinance_symbol)

        # ── Market data via fast_info (lighter, more reliable endpoint) ─────
        current_price = year_high = year_low = market_cap = None
        try:
            fast = ticker.fast_info
            current_price = getattr(fast, 'last_price', None)
            year_high     = getattr(fast, 'year_high', None)
            year_low      = getattr(fast, 'year_low', None)
            market_cap    = getattr(fast, 'market_cap', None)
        except Exception as e:
            print(f"[yfinance] fast_info error for {yfinance_symbol}: {type(e).__name__}: {e}", file=sys.stderr)

        # ── Company metadata via info (may be empty for some TASE tickers) ──
        name = sector = industry = description = dividend_yield = price_change_pct = None
        symbol = yfinance_symbol
        try:
            info = ticker.info
            for field in ['longName', 'shortName', 'displayName']:
                if info.get(field):
                    name = info[field]
                    break
            symbol           = info.get('symbol', yfinance_symbol)
            sector           = info.get('sector')
            industry         = info.get('industry')
            description      = info.get('longBusinessSummary')
            dividend_yield   = info.get('dividendYield')
            price_change_pct = info.get('regularMarketChangePercent')
            # Prefer info price/range when fast_info didn't return them
            if current_price is None:
                current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if year_high is None:
                year_high = info.get('fiftyTwoWeekHigh')
            if year_low is None:
                year_low = info.get('fiftyTwoWeekLow')
            if market_cap is None:
                market_cap = info.get('marketCap')
        except Exception as e:
            print(f"[yfinance] info error for {yfinance_symbol}: {type(e).__name__}: {e}", file=sys.stderr)

        # Return None if we got nothing useful — prevents caching empty results
        if not any([name, current_price, sector, year_high]):
            print(f"[yfinance] no usable data for {yfinance_symbol}", file=sys.stderr)
            return None

        return {
            'name': name,
            'symbol': symbol,
            'sector': sector,
            'industry': industry,
            'description': description,
            'market_cap': market_cap,
            'fifty_two_week_high': year_high,
            'fifty_two_week_low': year_low,
            'dividend_yield': dividend_yield,
            'current_price': current_price,
            'price_change_pct': price_change_pct,
            'info_fetched_at': date.today().isoformat(),
        }
    except Exception as e:
        print(f"[yfinance] fatal error for {yfinance_symbol}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def get_yfinance_history(yfinance_symbol):
    """Fetch full price history from Yahoo Finance.

    Returns list of {date, close, volume} dicts sorted by date (ISO strings).
    Returns empty list on failure.
    """
    import sys
    try:
        import yfinance as yf
        ticker = yf.Ticker(yfinance_symbol)
        hist = ticker.history(period='max')
        if hist.empty:
            print(f"[yfinance] empty history for {yfinance_symbol}", file=sys.stderr)
            return []
        result = []
        for ts, row in hist.iterrows():
            result.append({
                'date': ts.strftime('%Y-%m-%d'),
                'close': round(float(row['Close']), 4),
                'volume': int(row.get('Volume', 0)),
            })
        return result
    except Exception as e:
        print(f"[yfinance] history error for {yfinance_symbol}: {type(e).__name__}: {e}", file=sys.stderr)
        return []


def _translate_text(text, target_lang='iw'):
    """Translate text using deep-translator (Google Translate, no API key needed).

    Returns translated string, or None on failure / empty input.
    Uses 'iw' (Google's code for Hebrew).
    """
    if not text:
        return None
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except Exception:
        return None


def ensure_hebrew_translations_cached(holding, force_refresh=False):
    """Translate sector/industry/description to Hebrew, caching in holding.yfinance_data.

    Translations are cached for 30 days (translation_fetched_at field).
    Returns the updated yfinance_data dict, or None if no yfinance data to translate.
    """
    from datetime import date, timedelta
    cached = holding.get('yfinance_data') or {}
    if not cached.get('sector') and not cached.get('description'):
        return None

    fetched_at = cached.get('translation_fetched_at')
    stale = True
    if fetched_at and not force_refresh:
        try:
            age = date.today() - date.fromisoformat(fetched_at)
            has_translation = any([cached.get('sector_he'), cached.get('description_he')])
            stale = age > timedelta(days=30) or not has_translation
        except ValueError:
            stale = True

    if not stale:
        return cached

    sector_he = _translate_text(cached.get('sector'))
    industry_he = _translate_text(cached.get('industry'))
    description = cached.get('description') or ''
    description_he = _translate_text(description[:4500])

    updates = {
        'sector_he': sector_he,
        'industry_he': industry_he,
        'description_he': description_he,
        'translation_fetched_at': date.today().isoformat(),
    }
    merged = {**cached, **updates}
    update_holding(holding.doc_id, yfinance_data=merged)
    return merged


def ensure_yfinance_info_cached(holding, force_refresh=False):
    """Return cached yfinance rich info for a holding, fetching if stale or missing.

    Successful results are cached for 7 days (info_fetched_at).
    Failed fetches are recorded with a 2-hour retry TTL (fetch_failed_at) so we
    don't hammer Yahoo Finance on every page load for bonds/delisted stocks.
    Returns the info dict, or None if holding has no yfinance mapping or fetch fails.
    """
    from datetime import date, datetime, timedelta
    tase_id = holding.get('tase_id')
    yfinance_symbol = get_yfinance_mapping(tase_id)
    if not yfinance_symbol:
        return None

    cached = holding.get('yfinance_data') or {}
    fetched_at = cached.get('info_fetched_at')

    stale = True
    if fetched_at and not force_refresh:
        try:
            age = date.today() - date.fromisoformat(fetched_at)
            stale = age > timedelta(days=7)
        except ValueError:
            stale = True
    elif cached.get('fetch_failed_at') and not force_refresh:
        # Within 2 hours of a recorded failure, skip the retry
        try:
            last_fail = datetime.fromisoformat(cached['fetch_failed_at'])
            stale = (datetime.now() - last_fail) > timedelta(hours=2)
        except ValueError:
            stale = True

    if stale:
        info = fetch_rich_info_from_yfinance(yfinance_symbol)
        if info:
            # Preserve existing keys (e.g. name/symbol set by set_yfinance_mapping)
            # Also clear any prior fetch_failed_at on success
            merged = {k: v for k, v in {**cached, **info}.items() if k != 'fetch_failed_at'}
            update_holding(holding.doc_id, yfinance_data=merged,
                           name_en=info.get('name'), ticker=info.get('symbol'))
            return merged
        # Fetch failed — record failure timestamp to rate-limit retries
        failure_record = {**cached, 'fetch_failed_at': datetime.now().isoformat()}
        update_holding(holding.doc_id, yfinance_data=failure_record)
        # Return stale successful data if we have it, otherwise None
        return cached if cached.get('info_fetched_at') else None

    return cached
