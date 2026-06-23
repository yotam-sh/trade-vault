# TradeVault

Self-hosted, web-based portfolio tracker. Originally built for IBI brokerage (Tel Aviv Stock Exchange) with full Hebrew/RTL support, it now tracks **multiple isolated portfolios** in **multiple currencies** (e.g. an ILS TASE portfolio and a USD US-stocks portfolio side by side), with FIFO tax-lot accounting, daily P&L analytics, and benchmark comparison.

TradeVault is **web-only** — everything is driven from the browser UI (the old command-line interface was retired). The interface is the **Comet** design system: a four-section app (Overview · Analytics · Holdings · Activity) with a Quick-Add drawer, a position deep-dive drawer, light/themeable styling, and a Hebrew/English toggle.

Created with Claude Code.

## Features

### Portfolios & data
- **Multiple isolated portfolios** — each portfolio is its own database file. Create, rename, switch, or delete portfolios from the switcher in the top bar. Holdings, transactions, snapshots, tax lots, and view preferences are per-portfolio; market data (price cache, TASE ticker map, benchmark series) is shared.
- **Multi-currency** — each portfolio has its own currency (e.g. ILS, USD). All values, charts, and the currency symbol render in the active portfolio's currency.
- **TASE + non-TASE holdings** — import IBI/TASE Excel exports, or track manual / US-listed holdings that have no TASE security number. US daily data can be imported from CSV.
- **Quick-Add drawer** — record a buy, sell, deposit, or withdrawal from anywhere via the **Add** button in the top bar, with a live symbol search and a running total. No file needed.
- **Daily portfolio snapshots** — import daily holdings from brokerage exports; value changes are tracked over time.
- **FIFO tax lots** — automatic cost-basis tracking using First-In-First-Out for capital gains.
- **Trade interpolation** — position changes between daily snapshots are detected and inferred as buy/sell transactions (new positions, closed positions, and partial buys/sells on existing positions). Idle cash released by sales is extracted automatically so it shows up in portfolio value.
- **Price refresh with history backfill** — the refresh button fetches current prices and **backfills missing daily history** for each holding; a background scheduler keeps recent history current.
- **Deduplication** — SHA-256 file hashing prevents re-importing the same file; holdings are deduplicated by TASE ID.

### The four sections
- **Overview** (`/`) — total value, an equity-vs-net-invested value chart with deposit markers, a KPI strip (cost, cost change, realized YTD, all-time realized P/L, idle cash), an allocation-by-type donut, today's movers, and a holdings preview. Portfolio value includes idle cash.
- **Analytics** (`/analytics`) — cumulative return vs **seven optional benchmark indices** (S&P 500, Nasdaq-100, TA-125, TA-35, Nikkei 225, KOSPI 200, EURO STOXX 50 — sourced via yfinance, default set toggleable), monthly return, drawdown from peak, P&L by position, average return by weekday, allocation over time, and a **Portfolio Map treemap** grouped by security type.
- **Holdings** (`/positions`) — open and closed positions, **grouped by security type** with group subtotals. Columns are **sortable within each group** (group headers stay put), with live search. Clicking a row opens a **position deep-dive drawer** (value, P&L, mini price chart, FIFO lots, link to the full position page).
- **Activity** (`/activity`) — a unified timeline of buys, sells, deposits, withdrawals, and dividends with type-filter chips. Interpolated/importer-derived trades carry an **auto** badge. A single master **Edit** toggle reveals per-row pencils; each opens an inline editor to correct the trade **price** (recomputes the total, replays FIFO lots, and heals cash) or **delete** the trade.

### Analytics & accounting
- **Self-contained metrics** — net invested, cost change, realized/unrealized P&L, and tax estimates are computed from live DB data; no brokerage-specific file is required after initial import.
- **Auto-computed monthly summaries** — month-end balance and cost-change metrics generated on the fly from snapshots (net of withdrawals), with partial-month warnings when trading days are missing.
- **Closed-position tracking** — realized P&L for fully sold positions, including a Days-Held count.
- **Capital-gains tax** — per-year capital-gains calculation, loss carryover, and a "potential future tax" estimate on unrealized gains. Multi-sheet tax report export.
- **Israeli holiday calendar** — TASE trading-day awareness via the `holidays` library (public holidays, eves, and selected optional holidays). Monthly trading-day counts for partial-month detection come from this calendar, not weekday arithmetic.
- **Morning-balance import** — bulk-import historic morning-balance files (DDMMYYYY.xlsx), computing daily P&L from consecutive-day comparisons with quantity-aware logic.

### Names, symbols & display
- **Unified name management** — each holding stores up to six independently-sourced name variants — `name_he` (IBI Hebrew), `name_tase_he`, `name_tase_en` (TASE registry), `name_yf_long`, `name_yf_short` (Yahoo Finance), and `name_en` (manual override). Each source writes only its own field; nothing is silently overwritten.
- **Display preferences** — choose which name/symbol field each table column shows, per language, from `/settings/display` or a per-table ⚙ cog. Hebrew mode defaults to Hebrew TASE names/symbols; English mode to English.
- **TASE API integration** — fetches authoritative English and Hebrew names and symbols directly from the TASE public API (`api.tase.co.il`), plus the derived Yahoo Finance ticker. Triggered on name-change detection, per-position "Fetch from TASE", and bulk "Refresh All from TASE".
- **Yahoo Finance integration** — map securities to yfinance symbols to fetch English names, tickers, prices, 52-week range, sector/industry, and (in Hebrew mode) Google-translated company info. Name fields are only written through an explicit review workflow — never on page load.
- **Stock-name-change detection** — when a security renames on TASE, names and the Hebrew symbol are updated and English fields re-fetched; changes are logged in the import.

### Position pages
- **Individual position pages** — full breakdown per holding: current price, 52-week range, market stats, average cost, unrealized P&L, open FIFO lots, trade history, an interactive price chart with buy/sell markers (1W/1M/3M/6M/YTD/1Y/From Purchase/All), and a daily-P&L chart. Closed positions show realized P&L, average buy/sell prices, and a "what-if kept" value. An identity grid lists every name/symbol variant.
- **Name editing** — edit Hebrew/English names from the position page with a live yfinance search dropdown; saving requires typing the current Hebrew name exactly.

### Platform
- **Bilingual UI** — full Hebrew/English switching (cookie-persisted). UI chrome switches; stock data stays in its original language. RTL/LTR layout flips automatically.
- **Themeable** — the Comet design system uses CSS variables; charts re-render instantly on theme change.
- **IS 5568 / WCAG 2.1 AA accessibility** — keyboard navigation, skip link, ARIA landmarks/roles/live regions, visible focus, screen-reader announcements, and a dedicated `/accessibility` statement (Hebrew + English).
- **Per-session login (TOTP)** — optional time-based one-time-password gate; secret stored in a sidecar file outside the database.
- **Schema versioning & auto-migration** — the DB self-migrates on startup and after import/restore.
- **Library update reminders** — a bimonthly startup reminder; "Check for outdated packages" / "Upgrade all packages" from Maintenance.

## Prerequisites

- Python 3.10+ **or** Docker

## Installation

**Option A — Docker (recommended):**
```bash
git clone <repo-url>
cd TradeVault
cp .env.example .env          # edit SECRET_KEY at minimum
docker compose up -d
# Open http://localhost:2501
```
`db/` and `data/` are stored in named Docker volumes (`tradevault_db`, `tradevault_data`) so your data persists across container restarts and upgrades.

**Option B — plain Python:**
```bash
git clone <repo-url>
cd TradeVault
pip install -r requirements.txt
python server.py
# Open http://localhost:2501
```

No additional configuration needed. The database file (`db/db.json`) is created automatically on first run.

## Quick Start

Everything is driven from the web UI:

1. **Start the app** — `docker compose up -d` (or `python server.py`), then open `http://localhost:2501`.
2. **Pick (or create) a portfolio** — use the switcher in the top bar; each portfolio has its own currency. The default portfolio is created on first run.
3. **Get data in**, either way:
   - **Import a daily file** — on the Overview page, use the upload form: pick import type **Daily portfolio**, choose the `.xlsx` (or US `.csv`), set the date, and submit. (The same form imports **Trades** and **Morning balance** files.)
   - **Quick-Add** — click **Add** in the top bar to record a buy/sell/deposit/withdrawal directly.
4. **Explore** — Overview, Analytics, Holdings, and Activity are in the top nav; Daily Summary/Details, Portfolios, Display Settings, and Maintenance are under the settings (⚙) menu.

Operational tasks (reconcile, rebuild tax lots, sync holdings, repair, refresh Yahoo Finance, check/upgrade packages, set up login) live under **Settings → Maintenance**; database backup/restore is on the **Profile** page (`/admin`).

## The App

The UI is organized into **four primary sections** (top nav, and a bottom nav on mobile) plus a set of secondary pages under the settings (⚙) menu.

| Section | URL | Description |
|---------|-----|-------------|
| **Overview** | `/` | Total value, equity-vs-net-invested value chart (deposit markers), KPI strip (cost, cost change, realized YTD, all-time realized P/L, idle cash), allocation-by-type donut, today's movers, holdings preview, and the daily-file upload form |
| **Analytics** | `/analytics` | Cumulative return vs 7 optional benchmark indices, monthly return, drawdown from peak, P&L by position, average return by weekday, allocation over time, and the Portfolio Map treemap (grouped by type) |
| **Holdings** | `/positions` | Open + closed positions grouped by security type with subtotals; sortable-within-group columns; search; row click opens the position deep-dive drawer |
| **Activity** | `/activity` | Unified timeline of buys/sells/deposits/withdrawals/dividends with filter chips; master Edit toggle → inline price edit + delete for trades (auto badge on interpolated ones) |

Secondary pages (settings ⚙ menu):

| Page | URL | Description |
|------|-----|-------------|
| **Position detail** | `/position/<id>` | Full position view: price chart with buy/sell markers, company info, trade history, FIFO lots, daily-P&L chart, identity grid |
| **Daily Summary** | `/daily-summary` | Per-day totals with best/worst performers and a daily-P&L bar chart; click a date row to jump to Daily Details for that day |
| **Daily Details** | `/daily-details` | Per-security daily breakdown, pivots by security and date, security-type stacked bar |
| **Portfolios** | `/settings/portfolios` | Create / rename / set-default / delete portfolios; set each portfolio's currency |
| **Display Settings** | `/settings/display` | Per-column name/symbol source selector, per language |
| **Profile** | `/admin` | Database backup (download `db.json`) and restore; bulk "Refresh All from TASE" |
| **Maintenance** | `/maintenance` | Login & security (TOTP), data health (reconcile, rebuild lots), and ops (sync holdings, repair, refresh yfinance, rebuild history, check/upgrade packages) |
| **Accessibility** | `/accessibility` | IS 5568 / WCAG 2.1 AA statement (Hebrew + English) |

> **Top-bar actions:** portfolio switcher, **refresh prices** (with history backfill), **Add** (Quick-Add drawer), and the settings (⚙) menu (language, theme, secondary pages, app version).

Data exports remain available from the per-view download endpoints (`/export/<view>`, `/export/tax-report`); the standalone Export *page* was retired in v1.0 (`/exports` now redirects to Overview).

## Operations

Everything is driven from the web UI; there is no command-line interface.

### Multiple portfolios

Each portfolio is its own database file under `db/`. Switch the active portfolio, create, rename, set-default, or delete one from the **switcher in the top bar** (or the Portfolios page). Each portfolio has its **own currency**. Market data (yfinance price cache, TASE ticker map, benchmark series) is shared across all portfolios; everything else — holdings, transactions, snapshots, tax lots, view preferences — is per-portfolio. Login is global (one session covers all portfolios).

### Importing data

All file imports use the **upload form on the Overview page** (`/`): pick the import type, choose one or more files, set the date, and submit.

- **Daily portfolio** — a brokerage daily export (IBI `.xlsx`, or a US `.csv`). Creates/updates holdings, records per-security daily prices, and writes a portfolio snapshot. Position changes vs. the previous day are auto-interpolated into buy/sell transactions, and idle cash released by sales is captured. The import is rejected if zero rows parse or the day's total deviates more than 50% from the previous snapshot — tick **Override deviation guard** to force it.
- **Trades** — individual trade order files (`DDMMYYYY.xlsx`); creates buy/sell transactions.
- **Morning balance** — historic morning-balance files (`DDMMYYYY.xlsx`); computes daily P&L from consecutive-day comparisons (quantity-aware), skipping TASE weekends and Israeli holidays.

> For ad-hoc entries, use **Quick-Add** (top bar) to record a buy, sell, deposit, or withdrawal without a file. Trade **prices** can be corrected (or trades deleted) from the **Activity** page's Edit mode.

### Maintenance (Settings → Maintenance)

- **Data Health** — *reconcile* (verifies each snapshot's positions sum to its market value, `total_equity = market_value + cash`, and open tax-lot shares match positions) and *rebuild tax lots* (FIFO replay from the ledger; clears orphan/duplicate lots).
- **Data & Integrations** — *sync active holdings*, *repair morning-balance*, *repair interpolated trades* (optional from-date), *rebuild daily history*, *refresh Yahoo Finance data*, *check for outdated packages*, *upgrade all packages*, and the TASE name refresh.
- **Login & Security** — set up / disable per-session TOTP login (see below).

Per-holding **ticker / Yahoo Finance mapping** is set on each position page (setting a ticker also registers the yfinance mapping). **Database backup/restore** is on the **Profile** page (`/admin`): export downloads the live `db.json`; import validates the file, backs up the current DB, replaces it, and auto-migrates to the current schema.

### Per-session login (TOTP)

Open **Settings → Maintenance → Login & Security → Set up login**, scan the QR in any authenticator app, and enter a code to confirm. Login activates immediately (no restart). The secret is saved to a sidecar file on the db volume (`db/auth.json`), never inside the database, so it is excluded from exports/backups. Disable it from the same page. An explicit `TOTP_SECRET` environment variable, if set, always takes precedence. When no secret is configured, the login gate is disabled (local-only dev). Behind a reverse proxy / Cloudflare Tunnel, also set `TRUST_PROXY=true` so secure cookies and per-IP rate limiting work correctly.

### Recovery (when the web UI is unavailable)

The data is plain files on the db volume, so you can always recover by hand:

- **Locked out of login (TOTP)** — delete `db/auth.json` on the volume to clear the configured secret (the gate disables when no secret is set), or set/replace the `TOTP_SECRET` environment variable and restart, then set login up again from the Maintenance page.
- **App won't boot / corrupted DB** — restore a backup by replacing `db/db.json` (or the relevant per-portfolio file) on the volume with a known-good copy (exports live in `db/imports/`), then restart. Each portfolio is a single TinyDB JSON file.
- **Stuck dependencies after an upgrade** — in Docker, rebuild the image (the durable path); on a bare-metal install, run `pip install --upgrade -r requirements.txt` in the app's environment.

## Project Structure

```
TradeVault/
├── server.py               # Flask web server (port 2501, Gunicorn-compatible)
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image (python:3.12-slim, Gunicorn)
├── docker-compose.yml      # Compose stack with named volumes
├── .env.example            # Environment variable template
├── app/
│   ├── connection.py       # TinyDB singleton, per-portfolio DB routing & table constants
│   ├── portfolios.py       # Multi-portfolio registry (per-portfolio DB files, currency)
│   ├── schemas.py          # Table schemas & validation
│   ├── settings.py         # Key/value settings store (per-portfolio)
│   ├── holdings.py         # Security master registry
│   ├── manual_portfolio.py # Manual / non-TASE holdings & trade recording
│   ├── transactions.py     # Buy/sell/deposit/dividend CRUD + price editing
│   ├── daily_prices.py     # Per-security daily price records
│   ├── tax_lots.py         # FIFO tax-lot engine
│   ├── yfinance_cache.py   # yfinance data cache table (separate from holdings)
│   ├── snapshots.py        # Portfolio snapshot generation
│   ├── imports.py          # Import audit trail & dedup
│   ├── icons.py            # Inline SVG (lucide) icon set, exposed as tv_icon()
│   ├── i18n.py             # Hebrew/English translation strings
│   ├── lib_check.py        # Bimonthly library update reminder + check/upgrade
│   ├── queries.py          # Analytics facade (delegates to analytics/ modules)
│   ├── excel_importer.py   # Import facade (delegates to importers/ modules)
│   ├── export.py           # Excel/CSV export for all views
│   ├── db_backup.py        # Database export/import + schema migration
│   ├── analytics/          # Modular analytics layer
│   │   ├── portfolio_analytics.py   # Overview/portfolio value, P&L, movers, idle cash
│   │   ├── trade_analytics.py       # Activity timeline, trade & closed-position history
│   │   ├── benchmark_analytics.py   # 7-index benchmark series (yfinance, cached)
│   │   ├── daily_analytics.py       # Daily summary & detail views
│   │   ├── monthly_summary.py       # Auto-computed monthly summaries
│   │   ├── position_analytics.py    # Individual position data & yfinance integration
│   │   └── tax_calculator.py        # Capital-gains tax calculations
│   ├── importers/          # Modular import layer
│   │   ├── base_importer.py             # Base importer with deduplication
│   │   ├── daily_importer.py            # IBI/TASE daily portfolio imports
│   │   ├── us_daily_importer.py         # US daily CSV imports
│   │   ├── morning_balance_importer.py  # Morning-balance bulk imports
│   │   ├── position_tracker.py          # Position change detection / interpolation
│   │   ├── repair_tools.py              # Data repair and validation
│   │   └── trade_importer.py            # Trade file imports
│   └── utils/              # Shared utilities
│       ├── data_enrichment.py       # Centralized name/ticker/symbol enrichment
│       ├── date_utils.py            # TASE weekend schedule helpers
│       ├── file_utils.py            # File path and hash utilities
│       ├── holding_resolver.py      # Name-based holding matching
│       ├── trading_calendar.py      # Israeli holiday calendar (is_non_trading_day)
│       └── translation_service.py   # Yahoo Finance / translation integration
├── templates/
│   ├── base.html           # Comet shell: top nav, drawers (position + Quick-Add), mobile nav
│   ├── index.html          # Overview
│   ├── analytics.html      # Analytics
│   ├── holdings.html       # Holdings (open + closed, grouped by type)
│   ├── activity.html       # Activity timeline (inline price editing)
│   ├── position.html       # Individual position detail page
│   ├── daily_summary.html  # Daily summary
│   ├── daily_details.html  # Detailed daily breakdown
│   ├── portfolios.html     # Portfolio management
│   ├── settings_display.html # Display preferences
│   ├── admin.html          # Profile (backup/restore)
│   ├── maintenance.html    # Maintenance & security
│   ├── accessibility.html  # IS 5568 accessibility statement
│   ├── login.html          # TOTP login gate
│   └── partials/           # Shared chart/card partials
├── static/
│   ├── comet.css           # Comet design system (themeable CSS variables, RTL/LTR)
│   └── comet.js            # Sortable tables, search, chips, drawers, Quick-Add
├── asset/                  # Brand SVGs served via /asset/<name>
│   ├── tradevault-mark.svg
│   ├── tradevault-favicon.svg
│   └── tradevault-app-icon.svg
├── db/
│   ├── db.json             # Default portfolio (TinyDB; auto-created)
│   ├── portfolios/         # Additional per-portfolio DB files
│   ├── auth.json           # TOTP secret sidecar (not in the DB, not tracked)
│   └── imports/            # DB export backups and pre-import safety copies (not tracked)
└── data/                   # Your import files (not tracked in git)
    ├── daily_data/         # Daily portfolio exports, organized by month
    ├── morning_balance/    # Historic morning balance files (DDMMYYYY.xlsx)
    └── trades/             # Individual trade files (DDMMYYYY.xlsx)
```

> Some legacy templates/assets from the pre-Comet UI (`graphs.html`, `transactions.html`, `style.css`, `app.js`) may still be present for backward compatibility but are not part of the active four-section UI.

## Data Flow

```
Brokerage exports (IBI .xlsx / US .csv)  +  Quick-Add (web)
       │
       ▼
┌──────────────────┐     ┌──────────────┐
│  excel_importer   │────▶│   imports     │  (audit trail + dedup)
│  / importers/*    │     └──────────────┘
│                   │
│  daily file ──────┼───▶ holdings        (security master)
│                   │───▶ daily_prices     (per-security per-day)
│                   │───▶ snapshots        (portfolio totals)
│                   │───▶ tax_lots         (FIFO cost basis)
│                   │───▶ transactions     (interpolated buys/sells, idle cash)
│                   │
│  trade files /    │
│  Quick-Add  ──────┼───▶ transactions     (buy/sell/deposit/withdraw/dividend)
│                   │
│  morning bal. ────┼───▶ daily_prices + snapshots + transactions
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  analytics/*      │  get_overview() · get_analytics() · get_activity()
│  (via queries.py) │  daily/monthly summaries · closed positions · tax · benchmarks
└──────────────────┘
       │
       ▼
┌──────────────────┐
│     i18n.py       │  (Hebrew/English translations)
└──────────────────┘
       │
       ▼
   Flask views (Comet templates)
```

**Note:** The implementation uses a modular architecture; `excel_importer.py` and `queries.py` are facades that delegate to the specialized `app/importers/` and `app/analytics/` modules.

## Database

Uses TinyDB (a lightweight JSON document database). Each portfolio is a separate JSON file; the default portfolio lives at `db/db.json`, additional ones under `db/portfolios/`. Files are created automatically on first use.

### Tables (per portfolio)

| Table | Purpose |
|-------|---------|
| `holdings` | Security master — TASE ID, security type, currency, Hebrew/English TASE symbols, Yahoo Finance ticker, and six name fields (`name_he`, `name_tase_he`, `name_tase_en`, `name_yf_long`, `name_yf_short`, `name_en`) |
| `transactions` | All financial events (buys, sells, deposits, withdrawals, dividends) |
| `daily_prices` | Per-security per-day price and value records |
| `portfolio_snapshots` | End-of-day portfolio totals |
| `tax_lots` | FIFO cost-basis lots for capital-gains tracking |
| `yfinance_cache` | Cached Yahoo Finance data per holding (price, sector, description, translations) |
| `imports` | Audit trail of imported files (SHA-256 dedup) |
| `settings` | Key/value configuration (currency, yfinance mappings, display prefs, etc.) |

### Resetting a portfolio

Delete its JSON file (`db/db.json` for the default, or the relevant file under `db/portfolios/`) and re-import your data. The file is regenerated automatically.

## Import File Formats

### Daily portfolio — IBI (`data.xlsx`)

The standard IBI daily portfolio export. Expected Hebrew column headers include סוג נייר, מספר ני"ע, שם ני"ע, מטבע, כמות, שער, שווי שוק, עלות, רווח/הפסד, שינוי יומי, and others. Security types "תפ"ס" and "פח"ק" (tax-advantaged savings products) are automatically skipped.

### Daily portfolio — US (`.csv`)

A US-broker daily holdings CSV for USD portfolios — symbol, quantity, price, market value, and cost columns. Holdings without a TASE security number are tracked as manual/US holdings.

### Morning balance files (`DDMMYYYY.xlsx`)

Historic morning-balance exports from IBI; the filename encodes the date. Contains 11 columns (security name, quantity, price, market value, holding weight, average cost, cost basis, unrealized P&L %, FIFO cost, FIFO change %, FIFO change ILS). Holdings are matched by Hebrew name (exact, then substring, then component overlap). Rows named "מס לשלם", "מס עתידי", or "מגן מס" are skipped.

### Trade files (`DDMMYYYY.xlsx`)

Individual trade order files from IBI; the filename encodes the trade date. Contains security name, action (buy/sell), quantity, price, and execution status.

## Deployment

### Docker Compose (recommended)

Copy `.env.example` to `.env` and set `SECRET_KEY` to a random string. Then:

```bash
docker compose up -d
```

The compose file mounts two named volumes:
- `tradevault_db` → `/data/db` (the TinyDB databases; `DB_PATH=/data/db/db.json`)
- `tradevault_data` → `/app/data` (your import files)

To update to a newer image:
```bash
docker compose pull && docker compose up -d
```

> **Note:** Gunicorn runs with `--workers 1` because TinyDB's `CachingMiddleware` is not safe for concurrent writes across multiple worker processes.

### TrueNAS Scale

Use TrueNAS → Apps → Custom App, or SSH into the server and run `docker compose up -d` from the cloned repo directory. Point the volume paths to datasets on your ZFS pool if you prefer bind mounts over named volumes (see the commented example in `docker-compose.yml`).

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `tradevault-dev-key-change-in-production` | Flask session signing key — **change this** |
| `DEBUG` | `false` | Enable Flask debug mode |
| `PORT` | `2501` | Port the server listens on |
| `DB_PATH` | `db/db.json` (relative to project root) | Path to the default portfolio's TinyDB JSON file |
| `TOTP_SECRET` | _(unset)_ | If set, forces a fixed TOTP login secret (takes precedence over the sidecar) |
| `TRUST_PROXY` | `false` | Set `true` behind a reverse proxy / tunnel for secure cookies and per-IP rate limiting |

## Technical Notes

- **Comet design system**: The UI is built on `static/comet.css` (themeable CSS custom properties, RTL/LTR-aware) and `static/comet.js` (group-aware sortable tables, table search, filter chips, the position and Quick-Add drawers). Icons are inline lucide SVGs via the `tv_icon(name, size)` Jinja global from `app/icons.py`.
- **Multi-portfolio routing**: `app/connection.py` resolves the active portfolio (session-scoped) to its TinyDB file; `app/portfolios.py` manages the registry and per-portfolio currency. Market-data tables (price cache, TASE map, benchmark cache) are shared; all account data is per-portfolio.
- **Group-aware sorting**: `comet.js` `wireSortable` partitions a table's rows into segments delimited by `.tv-group-row` markers and sorts each segment's data rows independently, so grouped Holdings tables sort *within* each security-type group while the group headers stay in place. Flat (ungrouped) tables are a single segment.
- **Activity price editing**: The Activity timeline reuses the existing `update_transaction_price` / `delete_transaction` endpoints (`/api/transactions/<id>/update-price` and `/delete`). Editing a price recomputes the total, replays FIFO lots, and repairs cash via `recompute_after_trade_change`; editing an interpolated price promotes its `source` to manual.
- **Idle cash**: Cash released by sales detected during daily import is captured so portfolio value (equity) reflects it; the Overview includes idle cash in total equity.
- **Benchmarks**: `benchmark_analytics.py` fetches seven indices (TA-125, TA-35, S&P 500 `^GSPC`, Nasdaq-100 `^NDX`, Nikkei 225 `^N225`, KOSPI 200 `^KS200`, EURO STOXX 50 `^STOXX50E`) via yfinance, cached in settings with a TTL; the cache key is versioned and refetches when the index set changes.
- **Name source isolation**: Each of the six name fields has exactly one writer — `name_he` on IBI import, `name_tase_he`/`name_tase_en` by TASE API calls, `name_yf_long`/`name_yf_short` via the explicit yfinance review workflow, and `name_en` via the name edit panel. No page visit or background task writes a name field without user intent.
- **Display preferences**: The `display_name_prefs` setting stores per-language dicts mapping context IDs (e.g. `positions_open_name`, `daily_details_symbol`) to a name/symbol field key, injected into templates via a context processor and cached in `flask.g` per request. Defaults are language-aware.
- **Data enrichment**: `utils/data_enrichment.py` adds all six name fields plus `symbol` (Hebrew TASE symbol), `symbol_en` (English TASE symbol), and `ticker` to query results so display-preference lookups work everywhere.
- **TASE symbol fields**: Holdings store `tase_symbol` (Hebrew, required), `tase_symbol_en` (English, populated on TASE refresh), and `ticker` (yfinance symbol derived from `tase_symbol_en` — dots → hyphens, `.TA` appended).
- **Bilingual i18n**: All UI strings live in `app/i18n.py` as a flat dict of `{'he', 'en'}` values. A context processor injects translations, language code, and text direction into every template; JavaScript strings are passed via a `var T = …` JSON blob.
- **RTL/LTR**: The `<html>` tag gets `dir="rtl"`/`dir="ltr"` by language; CSS uses `[dir="ltr"]` selectors to flip layout. The top bar keeps a fixed orientation regardless of page direction.
- **TASE trading calendar**: `app/utils/trading_calendar.py` `is_non_trading_day()` combines weekend detection (handling the Sun-Thu→Mon-Fri switch on 2026-01-05) with Israeli public-holiday detection via the `holidays` library. All non-trading-day checks (import skipping, repair cleanup, analytics filtering) use this single function.
- **Morning-balance P&L**: computed as `market_value - prev_market_value` when quantity is stable; when quantity changes, only the price movement on `min(prev_qty, today_qty)` shares is counted, so purchases don't inflate P&L.
- **FIFO engine**: `tax_lots.py:sell_fifo()` consumes lots oldest-first, tracking remaining shares and realized P&L per lot.
- **Interpolation**: When a daily import detects position changes vs. the previous day, it creates buy/sell transactions (unless a nearby real trade exists) — new holdings (full buy), disappeared holdings (full sell), and quantity changes (partial buy/sell). "Repair interpolated trades" re-runs this from a given date with the latest logic.
- **Schema versioning & auto-migration**: `db_backup.py` maintains a `SCHEMA_VERSION`; `migrate_db()` runs pending migrations on every startup and after a DB import, then stamps the version, so restoring an old backup always yields a current schema.
- **yfinance cache isolation**: Yahoo Finance data is stored in a dedicated `yfinance_cache` table rather than inside holding records, keeping holdings lean and cache invalidation clean.
- **Currency normalization**: IBI exports currencies with trailing whitespace and codes (e.g. "שקל חדש                    000"), cleaned to standard codes (ILS, USD, EUR).
- **Date sorting**: table sort uses an ISO date regex guard (`/^\d{4}-\d{2}-\d{2}$/`) before falling back to `parseFloat`, so `YYYY-MM-DD` dates sort correctly.
- **Windows DB import**: `NamedTemporaryFile` on Windows keeps an exclusive handle open; the import route explicitly `close()`s before writing so `os.unlink` can succeed.
- **daily_prices deduplication**: duplicate price records are detected by `(holding_id, date)` rather than `(ticker, date)`, preventing spurious duplicates when a holding's ticker changes between imports.

## Credits

- Vibe coding, idea, fighting with Claude by [yotam-sh]
- Code by [Anthropic's Claude](https://claude.ai) (Claude Code)
- Logo by [OpenAI's ChatGPT](https://chatgpt.com)

## License

[MIT](LICENSE)
