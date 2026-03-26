"""Position analytics - per-security detail pages."""

from datetime import date

from app.holdings import get_holding, list_holdings
from app.transactions import list_transactions
from app.connection import get_table, DAILY_PRICES, TAX_LOTS
from app.analytics.portfolio_analytics import get_portfolio_value
from app.analytics.trade_analytics import get_closed_positions, get_trade_history
from app.utils.data_enrichment import enrich_position_with_holding
from app.utils.translation_service import (
    get_yfinance_mapping,
    ensure_yfinance_info_cached,
    get_yfinance_history,
    fetch_rich_info_from_yfinance,
)
from tinydb import Query


def get_positions_list():
    """Return open and closed positions for the /positions index page."""
    portfolio = get_portfolio_value()
    open_positions = []
    if portfolio:
        for pos in portfolio['positions']:
            if pos.get('quantity', 0) <= 0:
                continue
            holding = get_holding(pos['holding_id'])
            open_positions.append({
                'holding_id': pos['holding_id'],
                'name_he': pos.get('name_he', ''),
                'name_en': pos.get('name_en'),
                'symbol': pos.get('symbol', ''),
                'ticker': pos.get('ticker'),
                'security_type': pos.get('security_type', ''),
                'quantity': pos.get('quantity', 0),
                'market_value': pos.get('market_value', 0),
                'cost_basis': pos.get('cost_basis', 0),
                'unrealized_pnl': pos.get('market_value', 0) - pos.get('cost_basis', 0),
                'unrealized_pnl_pct': (
                    (pos.get('market_value', 0) - pos.get('cost_basis', 0))
                    / pos.get('cost_basis', 1) * 100
                    if pos.get('cost_basis') else 0
                ),
                'weight': pos.get('weight', 0),
                'first_bought': holding.get('first_bought') if holding else None,
                'days_holding': (
                    (date.today() - date.fromisoformat(holding['first_bought'])).days
                    if holding and holding.get('first_bought') else None
                ),
            })

    closed = get_closed_positions()

    return {'open': open_positions, 'closed': closed}


def get_top_positions_pnl():
    """Return all positions ranked by total P&L (realized + unrealized).

    Combines open unrealized P&L with closed realized P&L per holding.
    Returns list of {holding_id, name_he, name_en, total_pnl, cost_basis} sorted by total_pnl desc.
    """
    combined = {}  # holding_id -> {name_he, name_en, total_pnl, cost_basis}

    # Open positions: unrealized P&L
    portfolio = get_portfolio_value()
    if portfolio:
        for pos in portfolio['positions']:
            if pos.get('quantity', 0) <= 0:
                continue
            hid = pos['holding_id']
            unrealized = pos.get('market_value', 0) - pos.get('cost_basis', 0)
            combined[hid] = {
                'holding_id': hid,
                'name_he': pos.get('name_he', ''),
                'name_en': pos.get('name_en'),
                'symbol': pos.get('symbol', ''),
                'total_pnl': unrealized,
                'cost_basis': pos.get('cost_basis', 0),
            }

    # Add realized P&L from partial sells on still-open positions
    for cp in get_closed_positions():
        hid = cp.get('holding_id')
        if hid is None or hid not in combined:
            continue
        combined[hid]['total_pnl'] += cp.get('total_pnl', 0) or 0
        combined[hid]['cost_basis'] += cp.get('total_cost', 0) or 0

    result = sorted(combined.values(), key=lambda x: x['total_pnl'], reverse=True)
    # Add pnl_pct
    for entry in result:
        cb = entry.get('cost_basis', 0)
        entry['pnl_pct'] = round(entry['total_pnl'] / cb * 100, 2) if cb else 0
        entry['total_pnl'] = round(entry['total_pnl'], 2)
    return result


def get_position_data(holding_id):
    """Return all data for an individual position page.

    Returns None if the holding does not exist.
    """
    holding = get_holding(holding_id)
    if not holding:
        return None

    # ── Trades for this holding ──────────────────────────────────────────────
    all_trades = get_trade_history()
    trades = [t for t in all_trades if t.get('holding_id') == holding_id]

    # ── Daily prices for this holding (our own import data) ──────────────────
    dp_table = get_table(DAILY_PRICES)
    DP = Query()
    dp_records = dp_table.search(DP.holding_id == holding_id)
    daily_prices = sorted(dp_records, key=lambda r: r['date'])

    # ── Open FIFO tax lots ────────────────────────────────────────────────────
    lt_table = get_table(TAX_LOTS)
    LT = Query()
    open_lots = lt_table.search((LT.holding_id == holding_id) & (LT.is_closed == False))
    open_lots = sorted(open_lots, key=lambda l: l['buy_date'])

    today_str = date.today().isoformat()
    for lot in open_lots:
        try:
            delta = date.today() - date.fromisoformat(lot['buy_date'])
            lot['days_held'] = delta.days
        except (ValueError, KeyError):
            lot['days_held'] = None

    # ── Is position currently open? ───────────────────────────────────────────
    portfolio = get_portfolio_value()
    current_position = None
    if portfolio:
        for pos in portfolio['positions']:
            if pos.get('holding_id') == holding_id and pos.get('quantity', 0) > 0:
                current_position = pos
                break
    is_open = current_position is not None

    # ── Closed position summary (if applicable) ───────────────────────────────
    closed_positions = get_closed_positions()
    closed_summary = next(
        (c for c in closed_positions if c['holding_id'] == holding_id), None
    )

    # ── yfinance data ─────────────────────────────────────────────────────────
    tase_id = holding.get('tase_id')
    yfinance_symbol = get_yfinance_mapping(tase_id) or holding.get('ticker')

    yfinance_info = None
    price_history = None
    hypothetical = None

    if yfinance_symbol:
        yfinance_info = ensure_yfinance_info_cached(holding)
        if yfinance_info:
            holding['yfinance_data'] = yfinance_info  # sync in-memory state for translation
        price_history = get_yfinance_history(yfinance_symbol)

        # For closed positions: compute "what if kept" hypothetical
        if closed_summary and price_history:
            last_price = price_history[-1]['close']
            total_shares = closed_summary.get('total_shares', 0)
            total_sell_amount = closed_summary.get('total_cost', 0) + closed_summary.get('total_pnl', 0)
            hypothetical_value = round(last_price * total_shares, 2)
            opportunity_cost = round(hypothetical_value - total_sell_amount, 2)
            hypothetical = {
                'current_price': last_price,
                'hypothetical_value': hypothetical_value,
                'opportunity_cost': opportunity_cost,
                'opportunity_cost_pct': round(
                    opportunity_cost / total_sell_amount * 100, 2
                ) if total_sell_amount else 0,
            }

    return {
        'holding': holding,
        'holding_id': holding_id,
        'is_open': is_open,
        'current_position': current_position,
        'trades': trades,
        'daily_prices': daily_prices,
        'open_lots': open_lots,
        'closed_summary': closed_summary,
        'yfinance_symbol': yfinance_symbol,
        'yfinance_info': yfinance_info,
        'price_history': price_history,
        'hypothetical': hypothetical,
    }


def refresh_yfinance_info(holding_id):
    """Force-refresh yfinance info for a holding. Returns updated info dict or None."""
    holding = get_holding(holding_id)
    if not holding:
        return None

    tase_id = holding.get('tase_id')
    yfinance_symbol = get_yfinance_mapping(tase_id) or holding.get('ticker')
    if not yfinance_symbol:
        return None

    return ensure_yfinance_info_cached(holding, force_refresh=True)
