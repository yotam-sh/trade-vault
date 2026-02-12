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

# IBI.xlsx transaction columns
TRANSACTION_COLUMNS = {
    'תאריך': 'date',
    'פעולה': 'action',
    'סכום': 'amount',
    'יתרה': 'balance',
    'שינוי מעלות (%)': 'cost_change_pct',
    'שינוי מעלות (₪)': 'cost_change_ils',
    'הערות': 'notes',
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

# Transaction action type mapping
ACTION_TYPE_MAP = {
    'העברה ראשונית': 'deposit',
    'הפקדה': 'deposit',
    'סיכום חודש': 'month_summary',
    'משיכה': 'withdrawal',
    'דיבידנד': 'dividend',
    'קניה': 'buy',
    'מכירה': 'sell',
    'עמלה': 'fee',
    'מס': 'tax',
}

# IBI.xlsx summary labels (right-side panel)
SUMMARY_LABELS = {
    'סך הפקדות': 'total_deposits',
    'סך הפקדות לחישוב שינוי מעלות': 'deposits_for_change_calc',
    'שינוי מעלות (₪)': 'cost_change_ils',
    'שינוי מעלות (%)': 'cost_change_pct',
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


def get_action_type(raw):
    """Map Hebrew action to English transaction type."""
    if not raw or not isinstance(raw, str):
        return 'other'
    return ACTION_TYPE_MAP.get(raw.strip(), 'other')
