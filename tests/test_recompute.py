"""Recompute-on-mutation: edits/deletes reconcile tax lots, realized P&L, cash."""

from app.connection import get_db
from app.settings import init_default_settings
from app.holdings import add_holding
from app.transactions import add_buy, add_sell, update_transaction_price, delete_transaction
from app.tax_lots import create_lot, sell_fifo, rebuild_tax_lots, get_all_lots
from app.analytics.trade_analytics import get_trade_history
from app.recompute import recompute_after_trade_change


def _seed_two_buys_and_a_sell():
    """holding T.TA: buy 10@100, buy 10@200, sell 15@150 (FIFO realized = 250)."""
    get_db(); init_default_settings()
    hid = add_holding(tase_id=111, tase_symbol='T', name_he='נייר', security_type='stock',
                      currency='ILS', ticker='T.TA')
    b1 = add_buy('T.TA', hid, '2026-01-01', 10, 100)
    create_lot(holding_id=hid, ticker='T.TA', buy_transaction_id=b1,
               buy_date='2026-01-01', buy_price=100, shares=10)
    b2 = add_buy('T.TA', hid, '2026-01-02', 10, 200)
    create_lot(holding_id=hid, ticker='T.TA', buy_transaction_id=b2,
               buy_date='2026-01-02', buy_price=200, shares=10)
    details = sell_fifo('T.TA', 15, 150, '2026-01-03')
    s1 = add_sell('T.TA', hid, '2026-01-03', 15, 150, sell_lot_details=details)
    return hid, b1, b2, s1


def _sell_realized():
    sells = [t for t in get_trade_history() if t['type'] == 'sell']
    return sum(t['realized_pnl'] for t in sells)


def _open_shares():
    return sum(l['remaining_shares'] for l in get_all_lots() if not l['is_closed'])


def test_rebuild_reconstructs_lots_and_pnl():
    _seed_two_buys_and_a_sell()
    assert _sell_realized() == 250          # 10*(150-100) + 5*(150-200)
    assert _open_shares() == 5
    summary = rebuild_tax_lots()
    assert summary == {'buys': 2, 'sells': 1, 'unmatched_sells': 0}
    assert _sell_realized() == 250          # unchanged after a clean rebuild
    assert _open_shares() == 5


def test_edit_buy_price_recomputes_realized_pnl():
    _hid, b1, _b2, _s1 = _seed_two_buys_and_a_sell()
    update_transaction_price(b1, 120)       # first lot cost 100 -> 120
    recompute_after_trade_change()
    # 10*(150-120) + 5*(150-200) = 300 - 250 = 50
    assert _sell_realized() == 50


def test_delete_sell_reopens_lots():
    _hid, _b1, _b2, s1 = _seed_two_buys_and_a_sell()
    delete_transaction(s1)
    recompute_after_trade_change()
    assert _sell_realized() == 0
    assert _open_shares() == 20              # both buys fully open again
