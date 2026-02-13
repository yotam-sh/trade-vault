# TradeVault

Personal stock portfolio tracker for IBI brokerage (Tel Aviv Stock Exchange). Features a CLI for data management and a web dashboard for portfolio analytics.

Built for tracking Israeli securities with full Hebrew support, FIFO tax lot accounting, and daily P&L analytics.

Created with Claude Code.

## Features

- **Daily portfolio snapshots** — Import daily holdings from IBI Excel exports, track value changes over time
- **Transaction ledger** — Deposits, buys, sells with auto-computed monthly summaries derived from daily data
- **Auto-computed monthly summaries** — Month-end balance and cost-change metrics generated on-the-fly from portfolio snapshots, with partial-month warnings when trading days are missing
- **FIFO tax lots** — Automatic cost basis tracking using First-In-First-Out for capital gains
- **Morning balance import** — Bulk import historic morning balance files (DDMMYYYY.xlsx), computing daily P&L from consecutive-day comparisons with quantity-aware logic
- **Trade interpolation** — Detects position changes between daily snapshots and infers buy/sell transactions
- **Data repair** — CLI repair command fixes P&L miscalculations, backfills missing percentages, and removes non-trading days with TASE schedule awareness
- **Bilingual UI** — Full Hebrew/English language switching via a nav bar toggle, persisted in a cookie. All UI chrome switches; stock data stays in its original language
- **Web dashboard** — Five views: portfolio overview, general ledger, daily summary, detailed daily breakdown, trade history
- **Calendar date picker** — Filter any view by single date or date range
- **Pivot analytics** — Aggregations by security type and by date with subtotals
- **Best/worst performers** — Daily summary highlights top and bottom movers
- **Closed position tracking** — P&L summary for fully sold positions
- **Deduplication** — SHA-256 file hashing prevents re-importing the same file; holdings deduplicated by TASE ID

## Prerequisites

- Python 3.10+
- pip

## Installation

```bash
git clone <repo-url>
cd TradeVault
pip install flask tinydb pandas openpyxl
```

No additional configuration needed. The database file (`db/db.json`) is created automatically on first run.

## Quick Start

```bash
# 1. Import your first daily portfolio file
python main.py import daily "data/daily_data/feb_2026/data.xlsx" --date 2026-02-02

# 2. Import transaction history from IBI
python main.py import transactions data/IBI.xlsx

# 3. Import trade files
python main.py import trades data/trades/

# 4. View your portfolio
python main.py show portfolio

# 5. Launch the web dashboard
python server.py
# Open http://localhost:5000
```

## Project Structure

```
TradeVault/
├── main.py                 # CLI entry point
├── server.py               # Flask web server (port 5000)
├── app/
│   ├── connection.py       # TinyDB singleton & table constants
│   ├── schemas.py          # 8 table schemas & validation
│   ├── settings.py         # Key/value settings store
│   ├── holdings.py         # Security master registry
│   ├── transactions.py     # Buy/sell/deposit CRUD
│   ├── daily_prices.py     # Per-security daily price records
│   ├── tax_lots.py         # FIFO tax lot engine
│   ├── dividends.py        # Dividend tracking
│   ├── snapshots.py        # Portfolio snapshot generation
│   ├── imports.py          # Import audit trail & dedup
│   ├── queries.py          # Analytics & frontend view queries
│   ├── i18n.py             # Hebrew/English translation strings
│   ├── excel_importer.py   # Excel file parsing (daily, transactions, trades, morning balance)
│   └── column_map.py       # Hebrew-English column mappings
├── templates/
│   ├── index.html          # Dashboard
│   ├── transactions.html   # General ledger
│   ├── daily_summary.html  # Daily summary
│   ├── daily_details.html  # Detailed daily breakdown
│   └── trades.html         # Trade history
├── static/
│   ├── style.css           # Dark mode styling with RTL/LTR support
│   └── app.js              # Sorting, filtering, calendar picker
├── db/
│   └── db.json             # TinyDB database (auto-created)
└── data/                   # Your Excel data files (not tracked in git)
    ├── daily_data/         # Daily portfolio exports, organized by month
    ├── morning_balance/    # Historic morning balance files (DDMMYYYY.xlsx)
    ├── trades/             # Individual trade files (DDMMYYYY.xlsx)
    └── IBI.xlsx            # Transaction history export
```

## CLI Reference

### Importing data

**Import a daily portfolio file:**
```bash
python main.py import daily <filepath> --date YYYY-MM-DD
```
Parses an IBI daily portfolio Excel export. Creates/updates holdings, records daily prices for each security, and generates a portfolio snapshot for that date. Automatically detects and interpolates position changes (new buys or sells) compared to the previous day.

**Import transaction history:**
```bash
python main.py import transactions <filepath>
```
Parses the IBI transaction history Excel file (`IBI.xlsx`). Imports deposits, monthly summaries, and the broker's cost-change metrics from the right-side summary panel.

**Import trade files:**
```bash
# Single file
python main.py import trades <filepath>

# All files in a folder
python main.py import trades <folderpath>
```
Parses individual trade order files (format: `DDMMYYYY.xlsx`). Creates buy/sell transactions with execution details.

**Import morning balance files:**
```bash
python main.py import morning-balance <folderpath>
```
Bulk imports historic morning balance Excel files (`DDMMYYYY.xlsx`) from a folder recursively. Processes files chronologically, computing daily P&L from consecutive-day comparisons. Quantity changes between days (buys/sells) are handled correctly — only price movement on shares held across both days counts as P&L. Non-trading days (detected by zero P&L on TASE weekend days) are automatically skipped.

### Repairing data

```bash
python main.py repair morning-balance
```
Recomputes daily P&L and price change percentages for all morning balance imports, regenerates snapshots, and removes non-trading days. Safe to run multiple times (idempotent). Handles the TASE schedule change from Sun-Thu to Mon-Fri trading (effective 2026-01-05).

### Adding transactions manually

**Add a buy:**
```bash
python main.py add buy <ticker> <shares> <price> [--date YYYY-MM-DD]
```
Records a buy transaction and creates a FIFO tax lot. If `--date` is omitted, defaults to today.

**Add a sell:**
```bash
python main.py add sell <ticker> <shares> <price> [--date YYYY-MM-DD]
```
Records a sell transaction and consumes tax lots using FIFO ordering. Calculates realized P&L per lot.

**Add a deposit:**
```bash
python main.py add deposit <amount> [--date YYYY-MM-DD]
```
Records a cash deposit. Deposits can also be added through the web UI on the transactions page.

### Viewing data

**Portfolio summary:**
```bash
python main.py show portfolio
```
Shows total value, cost basis, unrealized P&L, daily P&L, and a table of all positions.

**Holdings list:**
```bash
python main.py show holdings [--all]
```
Lists all active securities. Use `--all` to include inactive (sold) holdings.

**P&L breakdown:**
```bash
python main.py show pnl
```
Shows unrealized and realized P&L, total deposits, dividends, and net return.

**Trade history:**
```bash
python main.py show trades
```
Lists all buy/sell transactions and closed position summaries.

### Setting tickers

```bash
python main.py set-ticker <search> <ticker>
```
Assigns a ticker symbol to a holding. `<search>` can be a TASE ID (number) or a Hebrew name fragment.

## Web Dashboard

Start the server:
```bash
python server.py
```
Open `http://localhost:5000` in your browser.

### Language switching

Click the language toggle button in the nav bar (rightmost in Hebrew mode, leftmost in English mode) to switch between Hebrew and English. The setting is saved in a cookie and persists across pages and sessions.

### Pages

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/` | Portfolio value, cost, P&L, positions table, daily file upload |
| **General** | `/transactions` | Deposit ledger with auto-computed monthly summaries, add deposit form, aggregate metrics |
| **Trades** | `/trades` | Buy/sell history with position labels, closed position P&L, capital gains tax |
| **Daily Summary** | `/daily-summary` | Per-day totals with best/worst performers |
| **Daily Details** | `/daily-details` | Per-security daily breakdown, pivots by security and date |

### Uploading daily files via the web

On the Dashboard (`/`), use the upload form at the top:
1. Select the date for the data
2. Choose the `.xlsx` file
3. Click Import

The file is saved to `data/daily_data/<month>_<year>/` and imported automatically.

### Adding deposits via the web

On the General page (`/transactions`), use the deposit form at the top:
1. Enter the amount
2. Pick a date using the calendar button (defaults to today)
3. Click Add Deposit

### Monthly summaries

Monthly summaries on the General page are computed automatically from your imported daily data. Each summary shows the month-end portfolio balance and cost-change metrics (ILS and %). If a month has fewer than 80% of expected TASE trading days, it is flagged with a "Partial" badge.

### Date filtering

The Daily Summary, Daily Details, and Trades pages have a calendar date picker:
- **Single day mode** — Click a date to filter to that day
- **Range mode** — Click a start date, then an end date
- **Presets** — Quick buttons for this week, this month, or last 30 days
- **Clear** — Remove the filter and show all data

The Daily Details page defaults to the most recent day when no filter is applied.

### Table features

- Click any column header to sort ascending/descending
- P&L values are color-coded: green for gains, red for losses
- On Daily Details, use the type dropdown to filter by security type (stocks, ETFs, bonds, mutual funds)
- Search box on Dashboard and Daily Details pages for filtering by security name

## Data Flow

```
IBI Excel exports
       │
       ▼
┌─────────────────┐     ┌──────────────┐
│ excel_importer   │────▶│   imports     │  (audit trail + dedup)
│                  │     └──────────────┘
│  daily file ─────┼───▶ holdings        (security master)
│                  │───▶ daily_prices     (per-security per-day)
│                  │───▶ snapshots        (portfolio totals)
│                  │───▶ tax_lots         (FIFO cost basis)
│                  │───▶ transactions     (interpolated buys/sells)
│                  │
│  IBI.xlsx ───────┼───▶ transactions     (deposits, summaries)
│                  │───▶ settings         (ibi_summary metrics)
│                  │
│  trade files ────┼───▶ transactions     (buy/sell with details)
│                  │
│  morning bal. ───┼───▶ daily_prices     (historic per-security)
│                  │───▶ snapshots        (historic portfolio totals)
│                  │───▶ transactions     (interpolated buys/sells)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│    queries.py    │  (analytics layer)
│                  │
│  get_portfolio_value()
│  get_transaction_log()     (+ computed monthly summaries)
│  get_daily_summary()
│  get_daily_details()
│  get_pivot_by_security()
│  get_pivot_by_date()
│  get_trade_history()
│  get_closed_positions()
└─────────────────┘
       │
       ▼
┌─────────────────┐
│     i18n.py      │  (Hebrew/English translations)
└─────────────────┘
       │
       ▼
   Flask views / CLI output
```

## Database

Uses TinyDB (a lightweight JSON document database). The database file is created at `db/db.json` on first run.

### Tables

| Table | Purpose |
|-------|---------|
| `holdings` | Security master registry (name, TASE ID, type, ticker) |
| `transactions` | All financial events (buys, sells, deposits, summaries) |
| `daily_prices` | Per-security per-day price and value snapshots |
| `portfolio_snapshots` | End-of-day portfolio totals |
| `tax_lots` | FIFO cost basis lots for capital gains tracking |
| `dividends` | Dividend payment records |
| `imports` | Audit trail of imported files (SHA-256 dedup) |
| `settings` | Key/value configuration (currency, ticker map, etc.) |

### Resetting the database

Delete `db/db.json` and re-import your data files. The file is regenerated automatically.

## Excel File Formats

### Daily portfolio (`data.xlsx`)

The standard IBI daily portfolio export. Expected Hebrew column headers include:

סוג נייר, מספר ני"ע, שם ני"ע, מטבע, כמות, שער, שווי שוק, עלות, רווח/הפסד, שינוי יומי, and others.

Security types "תפ"ס" and "פח"ק" (tax-advantaged savings products) are automatically skipped.

### Transaction history (`IBI.xlsx`)

The IBI account statement export. Left side contains transaction rows (date, action, amount, balance). Right side contains summary metrics (total deposits, cost change).

### Morning balance files (`DDMMYYYY.xlsx`)

Historic morning balance exports from IBI. Filename encodes the date. Contains 11 columns: security name, quantity, price, market value, holding weight, average cost, cost basis, unrealized P&L %, FIFO cost, FIFO change %, FIFO change ILS. Holdings are matched to the database by Hebrew name (exact match, then substring, then component overlap). Rows named "מס לשלם", "מס עתידי", or "מגן מס" are skipped.

### Trade files (`DDMMYYYY.xlsx`)

Individual trade order files from IBI. Filename encodes the trade date. Contains order details: security name, action (buy/sell), quantity, price, execution status.

## Technical Notes

- **Bilingual i18n**: All UI strings live in `app/i18n.py` as a flat dict mapping keys to `{'he': '...', 'en': '...'}` values. A Flask context processor injects the translations, language code, and text direction into every template. JavaScript strings are passed via a `<script>var T = ...;</script>` JSON blob.
- **RTL/LTR**: The `<html>` tag gets `dir="rtl"` or `dir="ltr"` based on the selected language. CSS uses `[dir="ltr"]` attribute selectors to flip layout properties (text alignment, border sides, dropdown anchoring).
- **TASE schedule awareness**: The codebase handles the TASE schedule change from Sun-Thu to Mon-Fri trading (effective 2026-01-05). Non-trading day detection, morning balance import skipping, and the repair command all use `_is_tase_weekend()` which checks the date against the correct schedule.
- **Morning balance P&L**: Daily P&L for morning balance imports is computed as `market_value - prev_market_value` when quantity is stable. When quantity changes (buys/sells), only the price movement on `min(prev_qty, today_qty)` shares is counted, preventing purchases from inflating P&L.
- **Auto-computed monthly summaries**: `queries.py:_compute_monthly_summaries()` groups portfolio snapshots by month, computes balance and cost-change metrics relative to cumulative deposits, and flags incomplete months using a TASE trading-day heuristic.
- **Hebrew encoding**: The CLI uses `io.TextIOWrapper` to force UTF-8 output on Windows consoles
- **Currency normalization**: IBI exports currencies with trailing whitespace and codes (e.g., "שקל חדש                    000") which are cleaned to standard codes (ILS, USD, EUR)
- **FIFO engine**: `tax_lots.py:sell_fifo()` consumes lots oldest-first, tracking remaining shares and realized P&L per lot
- **Interpolation**: When a daily import detects a new holding or a disappeared one compared to the previous day, it automatically creates buy/sell transactions (unless a nearby trade already exists)

## License

Private project - not for distribution.
