"""Monthly summary computation and transaction log views."""

import calendar
from app.snapshots import list_snapshots, get_latest_snapshot
from app.transactions import list_transactions, get_total_deposits, get_total_withdrawals


def _count_sun_thu_days(year, month):
    """Count Sunday-Thursday weekdays in a given month (TASE trading days)."""
    _, num_days = calendar.monthrange(year, month)
    count = 0
    for day in range(1, num_days + 1):
        # weekday(): Mon=0 .. Sun=6.  TASE trades Sun(6)-Thu(3)
        wd = calendar.weekday(year, month, day)
        if wd == 6 or wd <= 3:  # Sun, Mon, Tue, Wed, Thu
            count += 1
    return count


def _compute_monthly_summaries():
    """Compute monthly summaries on-the-fly from portfolio snapshots.

    Groups snapshots by month, computes balance and cost-change metrics,
    and flags months with incomplete trading-day coverage.
    """
    snapshots = list_snapshots()
    if not snapshots:
        return []

    deposits = list_transactions(type_='deposit')
    deposits.sort(key=lambda d: d['date'])
    withdrawals = list_transactions(type_='withdrawal')
    withdrawals.sort(key=lambda d: d['date'])

    # Group snapshots by YYYY-MM
    by_month = {}
    for snap in snapshots:
        month_key = snap['date'][:7]
        by_month.setdefault(month_key, []).append(snap)

    result = []
    for month_key in sorted(by_month):
        month_snaps = sorted(by_month[month_key], key=lambda s: s['date'])
        last_snap = month_snaps[-1]

        # Cumulative net invested up to end of this month
        cum_deposits = sum(
            d['total_amount'] for d in deposits if d['date'] <= last_snap['date']
        )
        cum_withdrawals = sum(
            w['total_amount'] for w in withdrawals if w['date'] <= last_snap['date']
        )
        net_invested = cum_deposits - cum_withdrawals

        balance = last_snap['total_market_value']
        cost_change_ils = balance - net_invested if net_invested else 0
        cost_change_pct = cost_change_ils / net_invested if net_invested else 0

        # Trading day completeness
        year, month = int(month_key[:4]), int(month_key[5:7])
        expected = _count_sun_thu_days(year, month)
        actual = len(month_snaps)

        result.append({
            'date': last_snap['date'],
            'balance': round(balance, 2),
            'cost_change_ils': round(cost_change_ils, 2),
            'cost_change_pct': cost_change_pct,
            'is_partial': actual < expected * 0.8,
            'trading_days': actual,
            'expected_days': expected,
        })

    return result


def get_transaction_log():
    """View 1: Transaction log (כללי) - deposits + computed month-end summaries.

    Deposits come from the transactions table.
    Monthly summaries are computed on-the-fly from portfolio snapshots.
    """
    all_txns = list_transactions()
    log = []

    for txn in all_txns:
        # Skip stored month_summary records — we compute these now
        if txn['type'] == 'month_summary':
            continue

        entry = {
            'date': txn['date'],
            'action': txn['type'],
            'amount': txn['total_amount'],
            'notes': txn.get('notes', ''),
        }

        entry['balance'] = None
        entry['cost_change_pct'] = txn.get('cost_change_pct')
        entry['cost_change_ils'] = txn.get('cost_change_ils')

        if txn['type'] == 'deposit':
            entry['action_key'] = 'action_deposit'
            if txn.get('notes') and '250' in str(txn.get('notes', '')):
                entry['action_key'] = 'action_initial_transfer'
        elif txn['type'] == 'withdrawal':
            entry['action_key'] = 'action_withdrawal'
        else:
            entry['action_key'] = txn['type']

        log.append(entry)

    # Inject computed monthly summaries
    for ms in _compute_monthly_summaries():
        log.append({
            'date': ms['date'],
            'action': 'month_summary',
            'action_key': 'action_month_summary',
            'amount': None,
            'balance': ms['balance'],
            'cost_change_pct': ms['cost_change_pct'],
            'cost_change_ils': ms['cost_change_ils'],
            'notes': '',
            'is_partial': ms['is_partial'],
            'trading_days': ms['trading_days'],
            'expected_days': ms['expected_days'],
        })

    log.sort(key=lambda e: e['date'])
    return log


def get_transaction_summary():
    """Right-panel aggregate metrics for transactions view.

    Computed entirely from live DB data — no dependency on IBI.xlsx imports.
    """
    total_deposits = get_total_deposits()
    total_withdrawals = get_total_withdrawals()
    net_invested = round(total_deposits - total_withdrawals, 2)

    snap = get_latest_snapshot()
    current_value = snap['total_market_value'] if snap else 0

    cost_change_ils = round(current_value - net_invested, 2)
    cost_change_pct = (cost_change_ils / net_invested) if net_invested else 0

    return {
        'total_deposits': total_deposits,
        'net_invested': net_invested,
        'cost_change_ils': cost_change_ils,
        'cost_change_pct': cost_change_pct,
    }
