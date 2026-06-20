"""Holdings CRUD - Master Security Registry."""

from tinydb import Query
from app.connection import get_table, HOLDINGS
from app.schemas import now_iso, validate_record, validate_update

# Non-TASE / manually-added holdings get a synthetic tase_id in this reserved range
# so they never collide with real TASE security numbers (which are well below this).
SYNTHETIC_TASE_BASE = 9_000_000_000


def _next_synthetic_tase_id(table):
    """Allocate the next free synthetic tase_id (>= SYNTHETIC_TASE_BASE)."""
    syn = [h.get('tase_id') or 0 for h in table.all()
           if (h.get('tase_id') or 0) >= SYNTHETIC_TASE_BASE]
    return (max(syn) + 1) if syn else SYNTHETIC_TASE_BASE


def add_holding(tase_id=None, tase_symbol=None, name_he=None, security_type='stock',
                currency='ILS', ticker=None, **kwargs):
    """Add a new holding. Returns doc_id.

    `tase_id` is optional: real TASE securities pass their number (deduped by it);
    manual / non-TASE securities (e.g. US stocks) omit it and are deduped by `ticker`,
    receiving a synthetic id in the reserved SYNTHETIC_TASE_BASE range. Holdings
    without a real tase_id are flagged `manual=True`.
    """
    table = get_table(HOLDINGS)
    H = Query()

    # Dedup: real TASE id → by tase_id; non-TASE → by ticker (when provided).
    if tase_id is not None:
        existing = table.search(H.tase_id == tase_id)
        if existing:
            return existing[0].doc_id
    elif ticker:
        existing = table.search(H.ticker == ticker)
        if existing:
            return existing[0].doc_id

    is_manual = kwargs.get('manual', tase_id is None)
    if tase_id is None:
        tase_id = _next_synthetic_tase_id(table)

    # name_he / tase_symbol are schema-required; fall back to ticker for non-TASE.
    name_he = name_he or ticker or str(tase_id)
    tase_symbol = tase_symbol or ticker or name_he

    now = now_iso()
    record = {
        'ticker': ticker,
        'tase_id': tase_id,
        'tase_symbol': tase_symbol,
        'name_he': name_he,
        'name_en': kwargs.get('name_en'),
        'security_type': security_type,
        'currency': currency,
        'manual': is_manual,
        'exchange': kwargs.get('exchange', 'TASE'),
        'is_active': kwargs.get('is_active', True),
        'first_bought': kwargs.get('first_bought'),
        'last_sold': kwargs.get('last_sold'),
        'tags': kwargs.get('tags', []),
        'notes': kwargs.get('notes'),
        'created_at': now,
        'updated_at': now,
    }

    valid, errors = validate_record('holdings', record)
    if not valid:
        raise ValueError(f"Invalid holding record: {errors}")

    return table.insert(record)


def get_holding(doc_id):
    """Get a holding by doc_id."""
    table = get_table(HOLDINGS)
    return table.get(doc_id=doc_id)


def get_holding_by_ticker(ticker):
    """Get a holding by Yahoo Finance ticker."""
    table = get_table(HOLDINGS)
    H = Query()
    results = table.search(H.ticker == ticker)
    return results[0] if results else None


def get_holding_by_tase_id(tase_id):
    """Get a holding by TASE security number."""
    table = get_table(HOLDINGS)
    H = Query()
    results = table.search(H.tase_id == tase_id)
    return results[0] if results else None


def list_holdings(active_only=True):
    """List all holdings, optionally filtering to active only."""
    table = get_table(HOLDINGS)
    if active_only:
        H = Query()
        return table.search(H.is_active == True)
    return table.all()


def sync_active_holdings():
    """Set is_active per the latest snapshot's positions. Returns (activated, deactivated)."""
    from app.snapshots import get_latest_snapshot
    snapshot = get_latest_snapshot()
    if not snapshot:
        return 0, 0
    current = {p.get('holding_id') for p in snapshot.get('positions', [])
               if (p.get('quantity', 0) or 0) > 0 and p.get('holding_id')}
    activated = deactivated = 0
    for holding in list_holdings(active_only=False):
        should = holding.doc_id in current
        is_active = holding.get('is_active', False)
        if should and not is_active:
            update_holding(holding.doc_id, is_active=True)
            activated += 1
        elif not should and is_active:
            update_holding(holding.doc_id, is_active=False)
            deactivated += 1
    return activated, deactivated


def update_holding(doc_id, **kwargs):
    """Update a holding's fields."""
    table = get_table(HOLDINGS)
    kwargs['updated_at'] = now_iso()
    valid, errors = validate_update('holdings', kwargs)
    if not valid:
        raise ValueError(f"Invalid holding update: {errors}")
    table.update(kwargs, doc_ids=[doc_id])


def deactivate_holding(doc_id, last_sold=None):
    """Mark a holding as inactive."""
    update_holding(doc_id, is_active=False, last_sold=last_sold or now_iso())


def set_ticker(doc_id, ticker):
    """Set the Yahoo Finance ticker for a holding."""
    update_holding(doc_id, ticker=ticker)


def search_holdings(name_fragment):
    """Search holdings by Hebrew name fragment."""
    table = get_table(HOLDINGS)
    H = Query()
    return table.search(H.name_he.search(name_fragment))
