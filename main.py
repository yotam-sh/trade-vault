"""CLI entry point for my-stocks portfolio tracker."""

import argparse
import sys
import os
import io

# Fix Windows console encoding for Hebrew output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from app.connection import get_db, close_db
from app.settings import init_default_settings
from app.excel_importer import import_daily_portfolio, import_transactions, import_trades, import_trades_folder
from app.holdings import list_holdings, get_holding_by_ticker, set_ticker
from app.transactions import add_buy, add_sell, add_deposit
from app.tax_lots import create_lot, sell_fifo
from app.queries import get_portfolio_value, get_pnl_summary, get_trade_history, get_closed_positions
from app.schemas import today_iso


def cmd_import(args):
    """Handle import subcommand."""
    # Initialize DB and defaults
    get_db()
    init_default_settings()

    if args.type == 'daily':
        data_date = args.date or today_iso()
        result = import_daily_portfolio(args.file, data_date=data_date)
        if result['status'] == 'duplicate':
            print("Skipped: file already imported.")
        else:
            print(f"Import complete: {result['status']}")
    elif args.type == 'transactions':
        result = import_transactions(args.file)
        if result['status'] == 'duplicate':
            print("Skipped: file already imported.")
        else:
            print(f"Import complete: {result['status']}")
    elif args.type == 'trades':
        path = args.file
        if os.path.isdir(path):
            result = import_trades_folder(path)
        else:
            result = import_trades(path)
            if result['status'] == 'duplicate':
                print("Skipped: file already imported.")
            else:
                print(f"Import complete: {result['status']}")
    else:
        print(f"Unknown import type: {args.type}")

    close_db()


def cmd_add(args):
    """Handle add subcommand."""
    get_db()
    init_default_settings()

    if args.action == 'buy':
        ticker = args.ticker
        holding = get_holding_by_ticker(ticker)
        if not holding:
            print(f"Holding not found for ticker: {ticker}")
            print("Import a daily portfolio first or add the holding manually.")
            close_db()
            return

        shares = float(args.shares)
        price = float(args.price)
        date = args.date or today_iso()

        txn_id = add_buy(
            ticker=ticker,
            holding_id=holding.doc_id,
            date=date,
            shares=shares,
            price_per_share=price,
        )
        lot_id = create_lot(
            holding_id=holding.doc_id,
            ticker=ticker,
            buy_transaction_id=txn_id,
            buy_date=date,
            buy_price=price,
            shares=shares,
        )
        print(f"Buy recorded: {shares} shares of {ticker} @ {price} on {date}")
        print(f"  Transaction ID: {txn_id}, Tax lot created")

    elif args.action == 'sell':
        ticker = args.ticker
        holding = get_holding_by_ticker(ticker)
        if not holding:
            print(f"Holding not found for ticker: {ticker}")
            close_db()
            return

        shares = float(args.shares)
        price = float(args.price)
        date = args.date or today_iso()

        # FIFO sell
        try:
            sell_details = sell_fifo(ticker, shares, price, date)
        except ValueError as e:
            print(f"Error: {e}")
            close_db()
            return

        txn_id = add_sell(
            ticker=ticker,
            holding_id=holding.doc_id,
            date=date,
            shares=shares,
            price_per_share=price,
            sell_lot_details=sell_details,
        )

        total_realized = sum(d['realized_pnl'] for d in sell_details)
        print(f"Sell recorded: {shares} shares of {ticker} @ {price} on {date}")
        print(f"  Transaction ID: {txn_id}")
        print(f"  Realized P&L: {total_realized:.2f} ILS")
        for d in sell_details:
            print(f"    Lot {d['lot_id']}: {d['shares_sold']} shares, "
                  f"cost basis {d['cost_basis_per_share']:.2f}, "
                  f"P&L {d['realized_pnl']:.2f}")

    elif args.action == 'deposit':
        amount = float(args.amount)
        date = args.date or today_iso()
        txn_id = add_deposit(date=date, amount=amount)
        print(f"Deposit recorded: {amount} ILS on {date} (ID: {txn_id})")

    else:
        print(f"Unknown action: {args.action}")

    close_db()


def cmd_show(args):
    """Handle show subcommand."""
    get_db()
    init_default_settings()

    if args.view == 'portfolio':
        pv = get_portfolio_value()
        if not pv:
            print("No portfolio data. Import a daily file first.")
            close_db()
            return

        print(f"\nPortfolio Summary ({pv['date']})")
        print(f"{'='*50}")
        print(f"  Total Value:     {pv['total_value']:>12,.2f} ILS")
        print(f"  Total Cost:      {pv['total_cost']:>12,.2f} ILS")
        print(f"  Unrealized P&L:  {pv['unrealized_pnl']:>12,.2f} ILS ({pv['unrealized_pnl_pct']:.2f}%)")
        print(f"  Daily P&L:       {pv['daily_pnl']:>12,.2f} ILS")
        print(f"  Positions:       {pv['num_positions']:>12}")
        print()

        print(f"  {'Ticker':<15} {'Value':>12} {'Cost':>12} {'P&L':>10} {'Weight':>7}")
        print(f"  {'-'*15} {'-'*12} {'-'*12} {'-'*10} {'-'*7}")
        for pos in sorted(pv['positions'], key=lambda p: p.get('market_value', 0), reverse=True):
            ticker = pos.get('ticker', 'N/A')[:15]
            mv = pos.get('market_value', 0)
            cb = pos.get('cost_basis', 0)
            pnl = mv - cb
            weight = pos.get('weight', 0)
            print(f"  {ticker:<15} {mv:>12,.2f} {cb:>12,.2f} {pnl:>10,.2f} {weight:>6.1f}%")

    elif args.view == 'holdings':
        holdings = list_holdings(active_only=not args.all)
        print(f"\n{'Active' if not args.all else 'All'} Holdings:")
        print(f"{'='*60}")
        for h in holdings:
            status = "ACTIVE" if h['is_active'] else "INACTIVE"
            ticker = h.get('ticker') or 'N/A'
            print(f"  [{h.doc_id}] {h['name_he']} ({h['tase_symbol']}) "
                  f"- {ticker} [{h['security_type']}] {status}")

    elif args.view == 'pnl':
        summary = get_pnl_summary()
        print(f"\nP&L Summary")
        print(f"{'='*50}")
        for key, val in summary.items():
            if isinstance(val, float):
                print(f"  {key:<25} {val:>12,.2f}")
            else:
                print(f"  {key:<25} {val}")

    elif args.view == 'trades':
        trades = get_trade_history()
        if not trades:
            print("No trade history. Import trade files first.")
            close_db()
            return

        print(f"\nTrade History ({len(trades)} trades)")
        print(f"{'='*90}")
        print(f"  {'Date':<12} {'Action':<6} {'Name':<20} {'Qty':>8} {'Price':>10} {'Amount':>12} {'P&L':>10}")
        print(f"  {'-'*12} {'-'*6} {'-'*20} {'-'*8} {'-'*10} {'-'*12} {'-'*10}")
        for t in trades:
            name = (t.get('name_he') or t.get('ticker', ''))[:20]
            pnl = t.get('realized_pnl', 0) or 0
            pnl_str = f"{pnl:>10,.2f}" if pnl else ''
            print(f"  {t['date']:<12} {t['type']:<6} {name:<20} "
                  f"{t.get('shares', 0):>8,.0f} {t.get('price_per_share', 0):>10,.2f} "
                  f"{t.get('total_amount', 0):>12,.2f} {pnl_str}")

        closed = get_closed_positions()
        if closed:
            print(f"\nClosed Positions ({len(closed)})")
            print(f"{'='*80}")
            print(f"  {'Name':<20} {'Shares':>8} {'Avg Buy':>10} {'Avg Sell':>10} {'P&L':>12} {'%':>8}")
            print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*10} {'-'*12} {'-'*8}")
            for c in closed:
                name = c['name_he'][:20]
                pnl_pct = c.get('pnl_pct', 0) or 0
                print(f"  {name:<20} {c['total_shares']:>8,.0f} "
                      f"{c['avg_buy_price']:>10,.2f} {c['avg_sell_price']:>10,.2f} "
                      f"{c['total_pnl']:>12,.2f} {pnl_pct:>7.2f}%")

    else:
        print(f"Unknown view: {args.view}")

    close_db()


def cmd_set_ticker(args):
    """Set Yahoo Finance ticker for a holding."""
    get_db()
    from app.holdings import get_holding_by_tase_id, search_holdings

    holding = None
    # Try by tase_id
    try:
        holding = get_holding_by_tase_id(int(args.search))
    except ValueError:
        pass

    # Try by name search
    if not holding:
        results = search_holdings(args.search)
        if len(results) == 1:
            holding = results[0]
        elif len(results) > 1:
            print("Multiple matches found:")
            for h in results:
                print(f"  [{h.doc_id}] {h['name_he']} ({h['tase_symbol']})")
            print("Use a more specific search or tase_id.")
            close_db()
            return
        else:
            print(f"No holding found matching: {args.search}")
            close_db()
            return

    set_ticker(holding.doc_id, args.ticker)

    # Also update ticker_map in settings
    from app.settings import get_setting, set_setting
    ticker_map = get_setting('ticker_map', {})
    ticker_map[holding['tase_symbol']] = args.ticker
    set_setting('ticker_map', ticker_map)

    print(f"Set ticker for {holding['name_he']} -> {args.ticker}")
    close_db()


def main():
    parser = argparse.ArgumentParser(
        description='my-stocks: Personal portfolio tracker',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # import command
    p_import = subparsers.add_parser('import', help='Import Excel data')
    p_import.add_argument('type', choices=['daily', 'transactions', 'trades'],
                          help='Type of import')
    p_import.add_argument('file', help='Path to Excel file')
    p_import.add_argument('--date', help='Data date (YYYY-MM-DD), default: today')
    p_import.set_defaults(func=cmd_import)

    # add command
    p_add = subparsers.add_parser('add', help='Add a transaction')
    p_add_sub = p_add.add_subparsers(dest='action', help='Transaction type')

    p_buy = p_add_sub.add_parser('buy', help='Record a buy')
    p_buy.add_argument('ticker', help='Yahoo Finance ticker')
    p_buy.add_argument('shares', help='Number of shares')
    p_buy.add_argument('price', help='Price per share')
    p_buy.add_argument('--date', help='Transaction date (YYYY-MM-DD)')

    p_sell = p_add_sub.add_parser('sell', help='Record a sell')
    p_sell.add_argument('ticker', help='Yahoo Finance ticker')
    p_sell.add_argument('shares', help='Number of shares')
    p_sell.add_argument('price', help='Price per share')
    p_sell.add_argument('--date', help='Transaction date (YYYY-MM-DD)')

    p_dep = p_add_sub.add_parser('deposit', help='Record a deposit')
    p_dep.add_argument('amount', help='Deposit amount')
    p_dep.add_argument('--date', help='Transaction date (YYYY-MM-DD)')

    p_add.set_defaults(func=cmd_add)

    # show command
    p_show = subparsers.add_parser('show', help='Show portfolio data')
    p_show.add_argument('view', choices=['portfolio', 'holdings', 'pnl', 'trades'],
                        help='What to display')
    p_show.add_argument('--all', action='store_true',
                        help='Include inactive holdings')
    p_show.set_defaults(func=cmd_show)

    # set-ticker command
    p_ticker = subparsers.add_parser('set-ticker', help='Set Yahoo Finance ticker for a holding')
    p_ticker.add_argument('search', help='Holding name or tase_id to search for')
    p_ticker.add_argument('ticker', help='Yahoo Finance ticker to assign')
    p_ticker.set_defaults(func=cmd_set_ticker)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == '__main__':
    main()
