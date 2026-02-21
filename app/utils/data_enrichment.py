"""Data enrichment utilities - add holding information to records."""

from app.holdings import get_holding


def enrich_position_with_holding(position, holding_id=None):
    """Enrich a position record with holding name and symbol.

    Args:
        position: Position dict (from snapshot or daily price)
        holding_id: Optional holding ID (if None, reads from position['holding_id'])

    Returns:
        Enriched position dict with name_he and symbol fields
    """
    hid = holding_id or position.get('holding_id')
    holding = get_holding(hid) if hid else None

    enriched = dict(position)
    enriched['name_he'] = holding['name_he'] if holding else position.get('ticker', '')
    enriched['name_en'] = holding.get('name_en') if holding else None
    enriched['symbol'] = holding['tase_symbol'] if holding else position.get('ticker', '')
    enriched['ticker'] = holding.get('ticker') if holding else None  # Yahoo Finance ticker
    enriched['security_type'] = holding.get('security_type', 'other') if holding else 'other'

    return enriched


def enrich_positions_batch(positions, holding_id_key='holding_id'):
    """Enrich multiple positions with holding info using a cache.

    More efficient than calling enrich_position_with_holding in a loop
    because it caches holding lookups.

    Args:
        positions: List of position dicts
        holding_id_key: Key name for holding ID in each position (default: 'holding_id')

    Returns:
        List of enriched position dicts
    """
    # Build holdings cache
    holdings_cache = {}
    for pos in positions:
        hid = pos.get(holding_id_key)
        if hid and hid not in holdings_cache:
            h = get_holding(hid)
            holdings_cache[hid] = h

    # Enrich positions
    result = []
    for pos in positions:
        hid = pos.get(holding_id_key)
        holding = holdings_cache.get(hid, {}) or {}

        enriched = dict(pos)
        enriched['name_he'] = holding.get('name_he', pos.get('ticker', ''))
        enriched['name_en'] = holding.get('name_en')
        enriched['symbol'] = holding.get('tase_symbol', pos.get('ticker', ''))
        enriched['ticker'] = holding.get('ticker')  # Yahoo Finance ticker
        enriched['security_type'] = holding.get('security_type', 'other')

        result.append(enriched)

    return result


def enrich_trade_with_holding(trade, holding_id=None):
    """Enrich a trade transaction with holding name and symbol.

    Similar to enrich_position_with_holding but with fallback to existing
    name_he/symbol fields in the trade record.

    Args:
        trade: Trade transaction dict
        holding_id: Optional holding ID (if None, reads from trade['holding_id'])

    Returns:
        Enriched trade dict with name_he and symbol fields
    """
    hid = holding_id or trade.get('holding_id')
    holding = get_holding(hid) if hid else None

    enriched = dict(trade)

    if holding:
        enriched['name_he'] = holding['name_he']
        enriched['name_en'] = holding.get('name_en')
        enriched['symbol'] = holding.get('tase_symbol', '')
        enriched['ticker'] = holding.get('ticker')  # Yahoo Finance ticker
        enriched['security_type'] = holding.get('security_type', '')
    else:
        # Fallback to existing values
        enriched['name_he'] = trade.get('name_he', trade.get('ticker', ''))
        enriched['name_en'] = None
        enriched['symbol'] = trade.get('symbol', trade.get('ticker', ''))
        enriched['ticker'] = None
        enriched['security_type'] = trade.get('security_type', '')

    return enriched
