"""Reconciliation checks — assert the DB's derived state is internally consistent.

Exposed via Settings → Maintenance → Data Health. Returns a list of (severity, date, message) tuples;
'error' means a hard invariant is broken, 'warn' means a soft/expected-edge mismatch.
"""


def reconcile(tolerance=1.0):
    from app.snapshots import list_snapshots, get_latest_snapshot
    from app.tax_lots import get_all_lots

    issues = []

    for snap in list_snapshots():
        date = snap.get('date', '?')
        positions = snap.get('positions', []) or []
        pos_sum = round(sum((p.get('market_value', 0) or 0) for p in positions), 2)
        mv = round(snap.get('total_market_value', 0) or 0, 2)
        if abs(pos_sum - mv) > tolerance:
            issues.append(('error', date,
                           f'positions sum {pos_sum} != total_market_value {mv}'))

        cash = snap.get('cash_balance')
        equity = snap.get('total_equity')
        if cash is not None and equity is not None:
            if abs(equity - (mv + cash)) > 0.01:
                issues.append(('error', date,
                               f'total_equity {equity} != market_value+cash {round(mv + cash, 2)}'))

    # Open-lot shares vs current position quantity (per holding) on the latest snapshot.
    # 'warn' only: positions seeded from morning-balance imports can legitimately lack
    # tax lots (no buy transactions on record).
    latest = get_latest_snapshot()
    if latest:
        pos_qty = {}
        for p in latest.get('positions', []) or []:
            if (p.get('quantity', 0) or 0) > 0:
                pos_qty[p.get('holding_id')] = round(p.get('quantity', 0) or 0, 4)
        lot_qty = {}
        for lot in get_all_lots():
            if not lot.get('is_closed'):
                hid = lot.get('holding_id')
                lot_qty[hid] = round(lot_qty.get(hid, 0) + (lot.get('remaining_shares', 0) or 0), 4)
        for hid, qty in pos_qty.items():
            lq = lot_qty.get(hid, 0)
            if abs(lq - qty) > 0.01:
                issues.append(('warn', latest.get('date', '?'),
                               f'holding {hid}: open-lot shares {lq} != position qty {qty}'))

        # Phantom open lots: a holding with open lots that is NOT held in the latest
        # snapshot (closed at the broker / sold to zero, but its lots were never closed).
        # The snapshot looks fine, but lot-derived paths (price refresh, backfill) would
        # resurrect the position. Surfaced so it can be repaired (repair interpolated).
        for hid, lq in lot_qty.items():
            if lq > 0.01 and hid not in pos_qty:
                issues.append(('warn', latest.get('date', '?'),
                               f'holding {hid}: open-lot shares {lq} but not held in latest snapshot — phantom'))

    return issues
