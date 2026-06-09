"""Holding resolution utilities - fuzzy matching and get-or-create patterns."""

import re
from app.holdings import (
    list_holdings,
    get_holding_by_tase_id,
    add_holding,
    update_holding,
)

def find_holding_by_name(name_he):
    """Find an existing holding by Hebrew name, with fuzzy fallback.

    Matching strategy:
    1. Exact match on name_he
    2. Fuzzy: DB name contains file name or vice versa (handles
       reversed component order like "ת"א-ביטוח.IBI" vs "IBI.ת"א-ביטוח")
    3. Component overlap: Split on dots/hyphens and check if components match

    Args:
        name_he: Hebrew name to search for

    Returns:
        Holding document or None if not found
    """
    all_holdings = list_holdings(active_only=False)

    # 1. Exact match
    for h in all_holdings:
        if h.get('name_he') == name_he:
            return h

    # 2. Fuzzy: bidirectional substring
    name_clean = name_he.strip()
    for h in all_holdings:
        db_name = h.get('name_he', '')
        if name_clean in db_name or db_name in name_clean:
            return h

    # 3. Fuzzy: split on dots and hyphens, check component overlap
    name_parts = set(re.split(r'[.\-\s]+', name_clean))
    for h in all_holdings:
        db_name = h.get('name_he', '')
        db_parts = set(re.split(r'[.\-\s]+', db_name))
        if name_parts and db_parts and name_parts == db_parts:
            return h

    return None


def find_or_create_holding(tase_id, tase_symbol, name_he, security_type,
                           currency, quantity=0, update_active=True,
                           data_date=None):
    """Find holding by TASE ID or create if doesn't exist.

    Consolidates the repeated pattern of:
    1. Check if holding exists by TASE ID
    2. If not, look up ticker from settings
    3. Create new holding
    4. Update active status if needed

    Args:
        tase_id: TASE security ID number
        tase_symbol: TASE symbol
        name_he: Hebrew name
        security_type: Security type (stock, bond, etc.)
        currency: Currency code
        quantity: Current quantity (used to set is_active)
        update_active: Whether to update is_active status for existing holdings

    Returns:
        Tuple of (holding_id: int, is_new: bool, holding: dict)
    """
    # Check if holding exists
    holding = get_holding_by_tase_id(tase_id)

    if holding is None:
        # Create new holding
        doc_id = add_holding(
            tase_id=tase_id,
            tase_symbol=tase_symbol,
            name_he=name_he,
            security_type=security_type,
            currency=currency,
            ticker=None,
            is_active=quantity > 0,
        )

        # Fetch the newly created holding
        from app.holdings import get_holding
        holding = get_holding(doc_id)
        return doc_id, True, holding, None

    else:
        # Holding exists
        holding_id = holding.doc_id

        # Update active status if quantity changed
        if update_active:
            is_active = quantity > 0
            if holding['is_active'] != is_active:
                update_holding(holding_id, is_active=is_active)
                # Refresh holding after update
                from app.holdings import get_holding
                holding = get_holding(holding_id)

        # Detect name/symbol change
        name_changed = holding['name_he'] != name_he
        symbol_changed = tase_symbol and holding.get('tase_symbol') != tase_symbol
        name_change = None
        if name_changed or symbol_changed:
            holding_updated = holding.get('updated_at', '')[:10]
            if data_date and holding_updated and data_date < holding_updated:
                # Import data is older than the holding's last update — skip update
                pass
            else:
                field_updates = {}
                if name_changed:
                    field_updates['name_he'] = name_he
                if symbol_changed:
                    field_updates['tase_symbol'] = tase_symbol
                if name_changed:
                    name_change = {
                        'tase_id': tase_id,
                        'old_name_he': holding['name_he'],
                        'new_name_he': name_he,
                        'old_name_en': holding.get('name_en'),
                        'new_name_en': None,
                    }
                update_holding(holding_id, **field_updates)
                if name_changed:
                    # Try to refresh names: TASE first, yfinance fallback
                    try:
                        from app.utils.translation_service import fetch_data_from_tase, fetch_info_from_yfinance
                        tase_data = fetch_data_from_tase(tase_id)
                        if tase_data:
                            en_updates = {'name_tase_en': tase_data['name']}
                            if tase_data.get('name_tase_he'):
                                en_updates['name_tase_he'] = tase_data['name_tase_he']
                            if tase_data.get('tase_symbol_en'):
                                en_updates['tase_symbol_en'] = tase_data['tase_symbol_en']
                            if tase_data.get('ticker'):
                                en_updates['ticker'] = tase_data['ticker']
                                # Keep yfinance_map in sync (shared across portfolios)
                                from app.settings import get_shared_setting, set_shared_setting
                                yf_map = get_shared_setting('yfinance_map', {})
                                yf_map[str(tase_id)] = tase_data['ticker']
                                set_shared_setting('yfinance_map', yf_map)
                            update_holding(holding_id, **en_updates)
                            name_change['new_name_en'] = tase_data['name']
                        else:
                            old_ticker = holding.get('ticker')
                            if old_ticker:
                                info = fetch_info_from_yfinance(old_ticker)
                                if info and info.get('name'):
                                    update_holding(holding_id,
                                                   name_yf_long=info.get('name_long'),
                                                   name_yf_short=info.get('name_short'))
                                    name_change['new_name_en'] = info['name']
                    except Exception:
                        pass
                from app.holdings import get_holding
                holding = get_holding(holding_id)

        return holding_id, False, holding, name_change
