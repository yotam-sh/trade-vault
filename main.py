"""CLI entry point for TradeVault portfolio tracker."""

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
from app.importers import import_daily_portfolio, import_transactions, import_trades, import_trades_folder, import_morning_balance_folder, repair_morning_balance_pnl
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
    elif args.type == 'morning-balance':
        path = args.file
        if not os.path.isdir(path):
            print(f"Error: {path} is not a directory. Provide a folder path.")
            close_db()
            return
        result = import_morning_balance_folder(path)
        if result['status'] != 'empty':
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
            name_en = h.get('name_en')
            name_display = f"{h['name_he']}" + (f" / {name_en}" if name_en else "")
            print(f"  [{h.doc_id}] Paper #{h['tase_id']}: {name_display} ({h['tase_symbol']}) "
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


def cmd_repair(args):
    """Handle repair subcommand."""
    get_db()
    init_default_settings()

    if args.target == 'morning-balance':
        repair_morning_balance_pnl()
    else:
        print(f"Unknown repair target: {args.target}")

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


def cmd_sync_holdings(args):
    """Sync is_active flag with current portfolio positions."""
    get_db()
    init_default_settings()

    from app.snapshots import get_latest_snapshot
    from app.holdings import list_holdings, update_holding, get_holding

    # Get latest portfolio snapshot
    snapshot = get_latest_snapshot()
    if not snapshot:
        print("No portfolio snapshot found. Import daily data first.")
        close_db()
        return

    # Get holding IDs of current positions (quantity > 0)
    current_holding_ids = set()
    for pos in snapshot.get('positions', []):
        if pos.get('quantity', 0) > 0:
            holding_id = pos.get('holding_id')
            if holding_id:
                current_holding_ids.add(holding_id)

    print(f"Current portfolio has {len(current_holding_ids)} positions")
    print()

    # Get all holdings
    all_holdings = list_holdings(active_only=False)

    # Sync is_active flag
    activated = 0
    deactivated = 0

    for holding in all_holdings:
        should_be_active = holding.doc_id in current_holding_ids
        is_currently_active = holding.get('is_active', False)

        if should_be_active and not is_currently_active:
            # Activate holding
            update_holding(holding.doc_id, is_active=True)
            activated += 1
            print(f"✓ Activated: {holding['name_he']} (Paper #{holding['tase_id']})")
        elif not should_be_active and is_currently_active:
            # Deactivate holding
            update_holding(holding.doc_id, is_active=False)
            deactivated += 1
            print(f"✗ Deactivated: {holding['name_he']} (Paper #{holding['tase_id']})")

    print(f"\nSync complete:")
    print(f"  Activated:   {activated}")
    print(f"  Deactivated: {deactivated}")
    print(f"  Unchanged:   {len(all_holdings) - activated - deactivated}")

    close_db()


def cmd_refresh_yfinance(args):
    """Refresh stock info from existing yfinance mappings."""
    get_db()
    init_default_settings()

    from app.utils.translation_service import refresh_info_from_mappings, get_yfinance_mapping

    # Get all mappings
    mappings = get_yfinance_mapping()

    if not mappings:
        print("No yfinance mappings found. Use 'set-yfinance' to create mappings first.")
        close_db()
        return

    print(f"Found {len(mappings)} yfinance mappings")
    print("Refreshing stock info from Yahoo Finance...")
    print()

    # Refresh all mappings
    results = refresh_info_from_mappings()

    print(f"\nRefresh complete:")
    print(f"  Success: {results['success']}")
    print(f"  Failed:  {results['failed']}")

    if results['errors']:
        print(f"\nErrors:")
        for err in results['errors']:
            print(f"  - {err}")

    close_db()


def cmd_set_yfinance(args):
    """Map TASE paper number to Yahoo Finance symbol and fetch stock info."""
    get_db()
    init_default_settings()

    from app.utils.translation_service import set_yfinance_mapping
    from app.holdings import get_holding_by_tase_id

    # Get the holding to show current info
    holding = get_holding_by_tase_id(args.tase_id)
    if not holding:
        print(f"Error: No holding found with TASE ID {args.tase_id}")
        close_db()
        return

    print(f"Holding: {holding['name_he']}")
    print(f"TASE ID: {args.tase_id}")
    print(f"Yahoo Finance Symbol: {args.yfinance_symbol}")
    print()
    print("Fetching stock info from yfinance...")

    # Set the mapping and fetch the info
    result = set_yfinance_mapping(args.tase_id, args.yfinance_symbol)

    if result['success']:
        if result['name_en'] and result['ticker']:
            print(f"✓ Success!")
            print(f"  English Name: {result['name_en']}")
            print(f"  Ticker: {result['ticker']}")
        elif result['name_en']:
            print(f"✓ Success: {result['name_en']}")
            print(f"  (No ticker available)")
        else:
            print(f"✓ Mapping saved, but could not fetch info from yfinance")
            print(f"  Error: {result['error']}")
    else:
        print(f"✗ Failed: {result['error']}")

    close_db()


def main():
    parser = argparse.ArgumentParser(
        description='TradeVault: Personal portfolio tracker',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # import command
    p_import = subparsers.add_parser('import', help='Import Excel data')
    p_import.add_argument('type', choices=['daily', 'transactions', 'trades', 'morning-balance'],
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
                        help='[holdings only] Show all holdings (including inactive/closed positions)')
    p_show.set_defaults(func=cmd_show)

    # repair command
    p_repair = subparsers.add_parser('repair', help='Repair data issues')
    p_repair.add_argument('target', choices=['morning-balance'],
                          help='What to repair')
    p_repair.set_defaults(func=cmd_repair)

    # set-ticker command
    p_ticker = subparsers.add_parser('set-ticker', help='Set Yahoo Finance ticker for a holding')
    p_ticker.add_argument('search', help='Holding name or tase_id to search for')
    p_ticker.add_argument('ticker', help='Yahoo Finance ticker to assign')
    p_ticker.set_defaults(func=cmd_set_ticker)

    # sync-holdings command
    p_sync = subparsers.add_parser('sync-holdings',
                                   help='Sync is_active flag with current portfolio')
    p_sync.set_defaults(func=cmd_sync_holdings)

    # set-yfinance command
    p_yfinance = subparsers.add_parser('set-yfinance',
                                       help='Map TASE paper number to Yahoo Finance symbol')
    p_yfinance.add_argument('tase_id', type=int, help='TASE paper number (e.g., 1156926)')
    p_yfinance.add_argument('yfinance_symbol', help='Yahoo Finance symbol (e.g., GNRS.TA)')
    p_yfinance.set_defaults(func=cmd_set_yfinance)

    # refresh-yfinance command
    p_refresh = subparsers.add_parser('refresh-yfinance',
                                      help='Refresh stock info from existing yfinance mappings')
    p_refresh.set_defaults(func=cmd_refresh_yfinance)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == '__main__':
    main()
