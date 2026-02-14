"""Manual yfinance symbol mapping and English name fetching.

Allows users to manually map TASE paper numbers to Yahoo Finance symbols,
then fetches English stock names from yfinance.
"""

import yfinance as yf
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
