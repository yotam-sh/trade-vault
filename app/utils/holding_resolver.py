"""Holding resolution utilities - fuzzy matching and get-or-create patterns."""

import re
from app.holdings import (
    list_holdings,
    get_holding_by_tase_id,
    add_holding,
    update_holding,
)
from app.settings import get_setting


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
                           currency, quantity=0, update_active=True):
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
        ticker_map = get_setting('ticker_map', {})
        ticker = ticker_map.get(tase_symbol) or ticker_map.get(name_he)

        doc_id = add_holding(
            tase_id=tase_id,
            tase_symbol=tase_symbol,
            name_he=name_he,
            security_type=security_type,
            currency=currency,
            ticker=ticker,
            is_active=quantity > 0,
        )

        # Fetch the newly created holding
        from app.holdings import get_holding
        holding = get_holding(doc_id)
        return doc_id, True, holding

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

        return holding_id, False, holding
