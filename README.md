# TradeVault

Personal stock portfolio tracker for IBI brokerage (Tel Aviv Stock Exchange). Features a CLI for data management and a web dashboard for portfolio analytics.

Built for tracking Israeli securities with full Hebrew support, FIFO tax lot accounting, and daily P&L analytics.

Created with Claude Code.

## Features

- **Daily portfolio snapshots** — Import daily holdings from IBI Excel exports, track value changes over time
- **Transaction ledger** — Deposits and withdrawals with auto-computed monthly summaries derived from daily data; both can be entered via the web UI
- **Auto-computed monthly summaries** — Month-end balance and cost-change metrics generated on-the-fly from portfolio snapshots (net of withdrawals), with partial-month warnings when trading days are missing
- **Self-contained analytics** — All summary metrics (net invested, all-time cost change) computed from live DB data; no brokerage-specific Excel file required after initial import
- **FIFO tax lots** — Automatic cost basis tracking using First-In-First-Out for capital gains
- **Morning balance import** — Bulk import historic morning balance files (DDMMYYYY.xlsx), computing daily P&L from consecutive-day comparisons with quantity-aware logic
- **Trade interpolation** — Detects position changes between daily snapshots and infers buy/sell transactions; handles new positions, closed positions, and quantity changes on existing positions (partial buys/sells)
- **Data repair** — CLI repair commands fix P&L miscalculations, backfill missing percentages, remove non-trading days, and re-run trade interpolation from a given date
- **Bilingual UI** — Full Hebrew/English language switching via settings dropdown, persisted in a cookie. All UI chrome switches; stock data stays in its original language
- **Theming system** — 4 color palettes (Default, Crimson, Teal, Slate) with visual previews, instant switching via CSS variables, and cookie persistence
- **Web dashboard** — Six views: portfolio overview, general ledger, daily summary, detailed daily breakdown, trade history, and a dedicated graphs page
- **Interactive charts** — Chart.js 4 charts on every page: allocation donut on the dashboard (with percentage labels on each segment), daily P&L bar on the summary page (switchable between daily, weekly, and monthly granularity), security-type stacked bar on the daily details page, tax breakdown donut and closed-positions bar on the trades page, and portfolio value vs net invested + monthly return charts (switchable between cumulative total return and standalone monthly return) on the graphs page. All charts re-render instantly when you switch color themes
- **Calendar date picker** — Filter any view by single date or date range
- **Pivot analytics** — Aggregations by security type and by date with subtotals
- **Best/worst performers** — Daily summary highlights top and bottom movers
- **Closed position tracking** — P&L summary for fully sold positions
- **Yahoo Finance integration** — Map TASE securities to Yahoo Finance symbols to automatically fetch English names and tickers via yfinance API
- **Excel export** — Export any view (portfolio, transactions, trades, daily data) to Excel with one click, plus comprehensive tax report generation
- **Deduplication** — SHA-256 file hashing prevents re-importing the same file; holdings deduplicated by TASE ID
- **Portfolio Map** — Squarified treemap on the home page: open positions sized by market value, grouped by security type (stocks/funds), cell color shows daily gain (green) or loss (red); group headers display section name and aggregate daily P&L
- **Position type badges** — Trade Log marks each trade as opening / increase / closing / reduction with a color-coded badge (blue / green / red / amber)

## Prerequisites

- Python 3.10+
- pip

## Installation

```bash
git clone <repo-url>
cd TradeVault
pip install flask tinydb pandas openpyxl yfinance
```

No additional configuration needed. The database file (`db/db.json`) is created automatically on first run.

## Quick Start

```bash
# 1. Import your first daily portfolio file
python main.py import daily "data/daily_data/feb_2026/data.xlsx" --date 2026-02-02

# 2. (Optional) Import trade files
python main.py import trades data/trades/

# 4. View your portfolio
python main.py show portfolio

# 5. Launch the web dashboard — add deposits/withdrawals manually via the General page
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
│   ├── queries.py          # Analytics facade (imports from analytics/ modules)
│   ├── excel_importer.py   # Import facade (imports from importers/ modules)
│   ├── export.py           # Excel export functionality for all views
│   ├── i18n.py             # Hebrew/English translation strings
│   ├── column_map.py       # Hebrew-English column mappings
│   ├── analytics/          # Modular analytics layer
│   │   ├── daily_analytics.py      # Daily summary and detail views
│   │   ├── monthly_summary.py      # Auto-computed monthly summaries
│   │   ├── portfolio_analytics.py  # Portfolio value and P&L
│   │   ├── tax_calculator.py       # Capital gains tax calculations
│   │   └── trade_analytics.py      # Trade history and closed positions
│   ├── importers/          # Modular import layer
│   │   ├── base_importer.py            # Base importer with deduplication
│   │   ├── daily_importer.py           # Daily portfolio file imports
│   │   ├── morning_balance_importer.py # Morning balance bulk imports
│   │   ├── position_tracker.py         # Position change detection
│   │   ├── repair_tools.py             # Data repair and validation
│   │   └── trade_importer.py           # Trade file imports
│   └── utils/              # Shared utilities
│       ├── data_enrichment.py      # Centralized name/ticker enrichment
│       ├── date_utils.py           # TASE calendar and date helpers
│       ├── file_utils.py           # File path and hash utilities
│       ├── holding_resolver.py     # Name-based holding matching
│       └── translation_service.py  # Yahoo Finance API integration
├── templates/
│   ├── index.html          # Dashboard
│   ├── transactions.html   # General ledger
│   ├── daily_summary.html  # Daily summary
│   ├── daily_details.html  # Detailed daily breakdown
│   ├── trades.html         # Trade history
│   └── graphs.html         # Graphs & charts
├── static/
│   ├── style.css           # Dark mode styling with RTL/LTR support and CSS variable theming
│   ├── app.js              # Sorting, filtering, calendar picker, settings dropdown
│   ├── logo.svg            # Favicon
│   └── logo_with_name.svg  # Navigation header logo
├── db/
│   └── db.json             # TinyDB database (auto-created)
└── data/                   # Your Excel data files (not tracked in git)
    ├── daily_data/         # Daily portfolio exports, organized by month
    ├── morning_balance/    # Historic morning balance files (DDMMYYYY.xlsx)
    ├── trades/             # Individual trade files (DDMMYYYY.xlsx)
```

## CLI Reference

### Importing data

**Import a daily portfolio file:**
```bash
python main.py import daily <filepath> --date YYYY-MM-DD
```
Parses an IBI daily portfolio Excel export. Creates/updates holdings, records daily prices for each security, and generates a portfolio snapshot for that date. Automatically detects and interpolates position changes (new buys or sells) compared to the previous day.

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

```bash
python main.py repair interpolated [--from-date YYYY-MM-DD]
```
Clears all interpolated buy/sell transactions from the given date onwards, reverses their tax lot effects, then re-runs position-change inference with the latest logic. Use this after upgrading to a newer version of the interpolation engine. Default start date: `2026-02-02`. Safe to re-run.

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

### Yahoo Finance integration

**Map TASE security to Yahoo Finance symbol:**
```bash
python main.py set-yfinance <tase_id> <yfinance_symbol>
```
Maps a TASE paper number to a Yahoo Finance symbol (e.g., `GNRS.TA`, `TEVA.TA`) and automatically fetches the English stock name and ticker from the Yahoo Finance API. The mapping is stored in settings for future reference.

Example:
```bash
python main.py set-yfinance 1156926 GNRS.TA
```

**Refresh stock info from existing mappings:**
```bash
python main.py refresh-yfinance
```
Re-fetches English names and tickers for all securities that have been mapped to Yahoo Finance symbols. Useful for updating stock information after yfinance data changes.

## Web Dashboard

Start the server:
```bash
python server.py
```
Open `http://localhost:5000` in your browser.

### Settings & Theming

Click the gear icon (⚙) button in the top-left corner of the navigation bar to open the settings dropdown. The dropdown contains:

**Language selector:**
- Switch between Hebrew (עברית) and English
- The page reloads to apply translations
- The setting is saved in a cookie and persists across pages and sessions
- The dropdown automatically reopens after language switch for convenience

**Theme selector:**
- Choose from 4 color palettes:
  - **Default** — GitHub Dark theme (dark blue/gray with blue accents)
  - **Crimson** — Deep burgundy with coral accents
  - **Teal** — Ocean blues with bright teal accents
  - **Slate** — Warm grays with orange/amber accents
- Each theme shows a visual color preview
- Switching is instant (no page reload)
- The theme preference is saved in a cookie and persists across pages and sessions

### Pages

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/` | Portfolio value, cost, P&L, positions table, portfolio map treemap, allocation donut, daily file upload |
| **General** | `/transactions` | Deposit and withdrawal ledger with auto-computed monthly summaries, add deposit/withdrawal forms, aggregate metrics (net invested, all-time cost change) |
| **Trades** | `/trades` | Buy/sell history with position labels, closed position P&L, capital gains tax, tax breakdown donut, closed-positions bar chart |
| **Daily Summary** | `/daily-summary` | Per-day totals with best/worst performers, daily P&L bar chart with daily/weekly/monthly granularity toggle |
| **Daily Details** | `/daily-details` | Per-security daily breakdown, pivots by security and date, security-type stacked bar chart |
| **Graphs** | `/graphs` | Portfolio value vs net invested over time (line chart) and monthly return % bar chart with toggle between cumulative total return and standalone monthly return |

### Uploading daily files via the web

On the Dashboard (`/`), use the upload form at the top:
1. Select the date for the data
2. Choose the `.xlsx` file
3. Click Import

The file is saved to `data/daily_data/<month>_<year>/` and imported automatically.

### Portfolio Map

The Dashboard home page shows a **Portfolio Map** — a squarified treemap below the holdings table. Each rectangle represents one open position; its area is proportional to market value.

- Positions are grouped by security type (stocks, funds, other); each group has a visible header showing the group name and its aggregate daily P&L.
- Cell colour shifts from neutral grey toward green (daily gain) or red (daily loss), capped at ±3 %.
- Labels show the TASE symbol (or Yahoo Finance ticker in English mode) and the position's daily change percentage.
- The chart is responsive — it re-renders automatically when the browser window is resized.

### Charts

Each page includes contextual charts relevant to its data. All charts use [Chart.js 4](https://www.chartjs.org/) loaded from CDN (no install required) and re-render automatically when you switch color themes.

| Page | Chart | Type |
|------|-------|------|
| **Dashboard** | Portfolio allocation by security type with percentage labels | Donut |
| **Daily Summary** | Daily P&L over the filtered period — daily / weekly / monthly toggle | Bar (green/red) |
| **Daily Details** | P&L contribution by security type per day | Stacked bar |
| **Trades** | Tax breakdown (gross gains / loss offset / net tax) | Donut |
| **Trades** | Closed positions P&L % ranked | Horizontal bar |
| **Graphs** | Portfolio value vs net invested over time | Line |
| **Graphs** | Monthly return % — toggle between total return and standalone monthly return; partial-month indicator | Bar |

The **Graphs** page (`/graphs`) is the dedicated chart hub, showing long-term performance trends across all imported data.

### Adding deposits via the web

On the General page (`/transactions`), use the deposit form at the top-left:
1. Enter the amount
2. Pick a date using the calendar button (defaults to today)
3. Click Add Deposit

### Adding withdrawals via the web

On the General page (`/transactions`), use the withdrawal form at the top-right:
1. Enter the amount
2. Pick a date using the calendar button (defaults to today)
3. Click Add Withdrawal

### Summary panel

The right-side Summary panel on the General page shows metrics computed entirely from live DB data:
- **Total Deposits** — sum of all deposit transactions
- **Net Invested** — deposits minus withdrawals
- **Cost Change (₪ / %)** — current portfolio value minus net invested (all-time gain/loss)
- **Net Tax Payable** — estimated capital gains tax for the current year

No brokerage-specific import is required for these figures to be accurate.

### Monthly summaries

Monthly summaries on the General page are computed automatically from your imported daily data. Each summary shows the month-end portfolio balance and cost-change metrics relative to net invested (deposits minus withdrawals) up to that date. If a month has fewer than 80% of expected TASE trading days, it is flagged with a "Partial" badge.

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

### Exporting data

Each page has an Export button (📥) that downloads the current view as an Excel file:
- **Dashboard** — Exports current portfolio positions with values and P&L
- **General** — Exports deposit history and monthly summaries
- **Trades** — Exports all buy/sell transactions plus closed positions summary
  - **Tax Report** — Special multi-sheet Excel export with per-year capital gains calculations, loss carryover tracking, and comprehensive tax summary
- **Daily Summary** — Exports daily totals with best/worst performers
- **Daily Details** — Exports per-security daily breakdown (respects active date filter)

The export respects your current filters and language settings. Date ranges, security type filters, and search filters are all preserved in the exported data.

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

**Note:** This diagram shows the logical data flow. The actual implementation uses a modular architecture with `app/importers/` (daily, trades, morning balance) and `app/analytics/` (portfolio, monthly, daily, trades, tax) modules. The `excel_importer.py` and `queries.py` files act as facades that delegate to these specialized modules.

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

### Morning balance files (`DDMMYYYY.xlsx`)

Historic morning balance exports from IBI. Filename encodes the date. Contains 11 columns: security name, quantity, price, market value, holding weight, average cost, cost basis, unrealized P&L %, FIFO cost, FIFO change %, FIFO change ILS. Holdings are matched to the database by Hebrew name (exact match, then substring, then component overlap). Rows named "מס לשלם", "מס עתידי", or "מגן מס" are skipped.

### Trade files (`DDMMYYYY.xlsx`)

Individual trade order files from IBI. Filename encodes the trade date. Contains order details: security name, action (buy/sell), quantity, price, execution status.

## Technical Notes

- **Modular architecture**: The codebase uses a three-layer architecture with facades for backward compatibility. `app/importers/` contains specialized import modules (daily, trades, morning balance, repair tools). `app/analytics/` contains query modules (portfolio, daily, monthly, trades, tax). `app/utils/` provides shared utilities (data enrichment, holding resolution, Yahoo Finance integration). The top-level `excel_importer.py` and `queries.py` are facades that import from these modules.
- **Data enrichment**: The `utils/data_enrichment.py` module provides centralized logic for adding English names and tickers to query results. When language is set to English, all analytics functions automatically enrich their output with `name_en` and `ticker` fields from the holdings table, falling back to Hebrew names when English data is unavailable.
- **Bilingual i18n**: All UI strings live in `app/i18n.py` as a flat dict mapping keys to `{'he': '...', 'en': '...'}` values. A Flask context processor injects the translations, language code, and text direction into every template. JavaScript strings are passed via a `<script>var T = ...;</script>` JSON blob.
- **RTL/LTR**: The `<html>` tag gets `dir="rtl"` or `dir="ltr"` based on the selected language. CSS uses `[dir="ltr"]` attribute selectors to flip layout properties (text alignment, border sides, dropdown anchoring). The navigation bar forces LTR layout to keep settings button and logo in fixed positions regardless of page direction.
- **CSS theming**: The entire color system uses CSS variables (custom properties) defined in `:root` for the default theme and `[data-theme="..."]` attribute selectors for alternate palettes. The JavaScript theme switcher updates the `data-theme` attribute on the `<html>` element, triggering instant recoloring without page reload. Theme preference is persisted in a cookie. Chart.js charts use a `MutationObserver` on the `data-theme` attribute to read updated CSS variable values and re-render with the new palette immediately.
- **TASE schedule awareness**: The codebase handles the TASE schedule change from Sun-Thu to Mon-Fri trading (effective 2026-01-05). Non-trading day detection, morning balance import skipping, and the repair command all use `_is_tase_weekend()` which checks the date against the correct schedule.
- **Morning balance P&L**: Daily P&L for morning balance imports is computed as `market_value - prev_market_value` when quantity is stable. When quantity changes (buys/sells), only the price movement on `min(prev_qty, today_qty)` shares is counted, preventing purchases from inflating P&L.
- **Auto-computed monthly summaries**: `monthly_summary.py:_compute_monthly_summaries()` groups portfolio snapshots by month, computes balance and cost-change metrics relative to cumulative net invested (deposits minus withdrawals up to each month-end), and flags incomplete months using a TASE trading-day heuristic.
- **No brokerage dependency**: The Summary panel (`get_transaction_summary()`) computes all metrics — total deposits, net invested, cost change — from live transaction and snapshot data. Deposits and withdrawals are entered via the web UI or CLI; no brokerage-specific file import is needed.
- **Hebrew encoding**: The CLI uses `io.TextIOWrapper` to force UTF-8 output on Windows consoles
- **Currency normalization**: IBI exports currencies with trailing whitespace and codes (e.g., "שקל חדש                    000") which are cleaned to standard codes (ILS, USD, EUR)
- **FIFO engine**: `tax_lots.py:sell_fifo()` consumes lots oldest-first, tracking remaining shares and realized P&L per lot
- **Interpolation**: When a daily import detects position changes compared to the previous day, it automatically creates buy/sell transactions (unless a nearby real trade already exists). Three cases are handled: new holdings (full buy), disappeared holdings (full sell), and quantity changes on existing holdings (partial buy or partial sell). The `repair interpolated` command re-runs this inference from a given date with the latest logic

## Credits

- Vibe coding, idea, fighting with Claude by [yotam-sh]
- Code by [Anthropic's Claude](https://claude.ai) (Claude Code)
- Logo by [OpenAI's ChatGPT](https://chatgpt.com)

## License

[MIT](LICENSE)
