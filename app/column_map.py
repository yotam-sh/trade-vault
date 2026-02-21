"""Hebrew-to-English column mappings for IBI Excel imports."""

# data.xlsx daily portfolio columns
DAILY_COLUMNS = {
    'שם נייר': 'name',
    'מספר נייר': 'tase_id',
    'סימבול': 'symbol',
    'סוג נייר': 'security_type',
    'מטבע': 'currency',
    'כמות נוכחית': 'quantity',
    'שער': 'price',
    '% שינוי': 'price_change_pct',
    'שווי נוכחי': 'market_value',
    'רווח/הפסד יומי': 'daily_pnl',
    'שינוי מעלות': 'unrealized_pnl',
    'שינוי מעלות ב%': 'unrealized_pnl_pct',
    'עלות': 'cost_basis',
    'אחוז אחזקה': 'holding_weight_pct',
    'עלות FIFO בוקר': 'fifo_cost',
    '% ש.מעלות FIFO בוקר': 'fifo_change_pct',
    'ש.מעלות FIFO בשקלים בוקר': 'fifo_change_ils',
    'מ.ממוצע FIFO בוקר': 'fifo_avg_price',
}

# Trade history columns (DDMMYYYY.xlsx files from IBI)
TRADE_COLUMNS = {
    'שם נייר': 'name',
    'סימבול': 'symbol',
    'סטטוס': 'status',
    'ק/מ': 'action',
    'כמות': 'order_qty',
    'מחיר': 'order_price',
    'שווי הוראה/ביצוע': 'order_value',
    'כמות ביצוע': 'exec_qty',
    'מחיר ביצוע': 'exec_price',
    'שעת ביצוע': 'exec_time',
    'יתרה לביצוע': 'remaining',
    'טריגר': 'trigger',
    'ת.התחלה': 'start_date',
    'ת.סיום': 'end_date',
    'שעת קליטה': 'received_time',
    'מספר נייר': 'tase_id',
    'מטבע': 'currency',
    'סוג': 'order_type',
    'אסמכתא': 'reference',
    'סוג תוקף': 'validity',
    'מידע נוסף': 'info',
}

# Trade status mapping
TRADE_STATUS_MAP = {
    'ביצוע מלא': 'executed',
    'נקלט': 'received',
    'בוטל': 'cancelled',
}

# Trade action mapping
TRADE_ACTION_MAP = {
    'קניה': 'buy',
    'מכירה': 'sell',
}

# Morning balance (historic) columns
MORNING_BALANCE_COLUMNS = {
    'שם נייר': 'name',
    'כמות בוקר': 'quantity',
    'שער בוקר': 'price',
    'שווי בוקר': 'market_value',
    '% אחזקה': 'holding_weight_pct',
    'עלות ממוצעת לע"נ': 'avg_cost_per_share',
    'עלות משוקללת': 'cost_basis',
    '% ש.מעלות': 'unrealized_pnl_pct',
    'עלות FIFO': 'fifo_cost',
    '% ש.מעלות FIFO': 'fifo_change_pct',
    'ש.מעלות FIFO בשקלים': 'fifo_change_ils',
}

# Rows in morning balance that are not securities
MORNING_BALANCE_SKIP_NAMES = {'מס לשלם', 'מס עתידי', 'מגן מס'}

# Security type mapping
SECURITY_TYPE_MAP = {
    'מניות בש"ח': 'stock',
    'קרנות נאמנות': 'mutual_fund',
    'תעודות סל': 'etf',
    'אג"ח': 'bond',
    'אג"ח ממשלתי': 'bond',
    'תפ"ס/פח"ק': 'skip',  # Tax/savings - skip during import
}

# Currency mapping
CURRENCY_MAP = {
    'שקל חדש                    000': 'ILS',
    'שקל חדש': 'ILS',
    'דולר ארה"ב': 'USD',
    'דולר': 'USD',
    'אירו': 'EUR',
    'ILS': 'ILS',
    'USD': 'USD',
    'EUR': 'EUR',
}


def clean_currency(raw):
    """Convert Hebrew currency string to standard code."""
    if not raw or not isinstance(raw, str):
        return 'ILS'
    raw = raw.strip()
    return CURRENCY_MAP.get(raw, 'ILS')


def clean_percent(raw):
    """Convert percent string like '-2.12%' to float -2.12."""
    if raw is None or (isinstance(raw, float) and str(raw) == 'nan'):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace('%', '').replace(',', '')
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def get_security_type(raw):
    """Map Hebrew security type to English."""
    if not raw or not isinstance(raw, str):
        return 'other'
    return SECURITY_TYPE_MAP.get(raw.strip(), 'other')


