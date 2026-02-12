"""Internationalization module — Hebrew/English UI translations."""

import json

TRANSLATIONS = {
    # ── Navigation & Brand ──
    'brand':              {'he': 'תיק השקעות',   'en': 'Investment Portfolio'},
    'nav_home':           {'he': 'ראשי',         'en': 'Home'},
    'nav_transactions':   {'he': 'כללי',         'en': 'General'},
    'nav_trades':         {'he': 'עסקאות',       'en': 'Trades'},
    'nav_daily_summary':  {'he': 'סיכום יומי',   'en': 'Daily Summary'},
    'nav_daily_details':  {'he': 'יומי מלא',     'en': 'Full Daily'},

    # ── Common controls ──
    'pick_date':          {'he': 'בחר תאריך',        'en': 'Select Date'},
    'no_date_selected':   {'he': 'לא נבחר תאריך',    'en': 'No Date Selected'},
    'clear':              {'he': 'נקה',               'en': 'Clear'},
    'clear_date':         {'he': 'נקה תאריך',         'en': 'Clear Date'},
    'mode_single':        {'he': 'יום בודד',          'en': 'Single Day'},
    'mode_range':         {'he': 'טווח',              'en': 'Range'},
    'preset_week':        {'he': 'השבוע',             'en': 'This Week'},
    'preset_month':       {'he': 'החודש',             'en': 'This Month'},
    'preset_30':          {'he': '30 יום',            'en': '30 Days'},
    'search_placeholder': {'he': 'חיפוש נייר...',     'en': 'Search security...'},
    'label_date':         {'he': 'תאריך:',            'en': 'Date:'},
    'label_type':         {'he': 'סוג:',              'en': 'Type:'},
    'type_all':           {'he': 'הכל',               'en': 'All'},

    # ── Calendar day headers ──
    'day_sun': {'he': 'א', 'en': 'Sun'},
    'day_mon': {'he': 'ב', 'en': 'Mon'},
    'day_tue': {'he': 'ג', 'en': 'Tue'},
    'day_wed': {'he': 'ד', 'en': 'Wed'},
    'day_thu': {'he': 'ה', 'en': 'Thu'},
    'day_fri': {'he': 'ו', 'en': 'Fri'},
    'day_sat': {'he': 'ש', 'en': 'Sat'},

    # ── Calendar month names ──
    'month_1':  {'he': 'ינואר',   'en': 'January'},
    'month_2':  {'he': 'פברואר',  'en': 'February'},
    'month_3':  {'he': 'מרץ',     'en': 'March'},
    'month_4':  {'he': 'אפריל',   'en': 'April'},
    'month_5':  {'he': 'מאי',     'en': 'May'},
    'month_6':  {'he': 'יוני',    'en': 'June'},
    'month_7':  {'he': 'יולי',    'en': 'July'},
    'month_8':  {'he': 'אוגוסט',  'en': 'August'},
    'month_9':  {'he': 'ספטמבר',  'en': 'September'},
    'month_10': {'he': 'אוקטובר', 'en': 'October'},
    'month_11': {'he': 'נובמבר',  'en': 'November'},
    'month_12': {'he': 'דצמבר',   'en': 'December'},

    # ── Home page ──
    'page_overview':     {'he': 'סקירת תיק',        'en': 'Portfolio Overview'},
    'upload_title':      {'he': 'ייבוא קובץ יומי',   'en': 'Import Daily File'},
    'label_file':        {'he': 'קובץ:',             'en': 'File:'},
    'pick_file':         {'he': 'בחר קובץ',          'en': 'Choose File'},
    'no_file_selected':  {'he': 'לא נבחר קובץ',      'en': 'No File Selected'},
    'btn_import':        {'he': 'ייבא',              'en': 'Import'},
    'stat_total_value':  {'he': 'שווי תיק',          'en': 'Portfolio Value'},
    'stat_cost':         {'he': 'עלות',              'en': 'Cost'},
    'stat_cost_change':  {'he': 'שינוי מעלות',       'en': 'Cost Change'},
    'stat_daily_pnl':    {'he': 'רווח/הפסד יומי',    'en': 'Daily Profit/Loss'},
    'stat_num_positions': {'he': 'מספר אחזקות',      'en': 'Number of Positions'},
    'stat_data_date':    {'he': 'תאריך נתונים',      'en': 'Data Date'},
    'holdings_title':    {'he': 'אחזקות',            'en': 'Holdings'},
    'th_name':           {'he': 'שם',                'en': 'Name'},
    'th_symbol':         {'he': 'סימבול',             'en': 'Symbol'},
    'th_value_ils':      {'he': 'שווי (₪)',          'en': 'Value (₪)'},
    'th_cost_ils':       {'he': 'עלות (₪)',          'en': 'Cost (₪)'},
    'th_pnl_ils':        {'he': 'רווח/הפסד (₪)',     'en': 'Profit/Loss (₪)'},
    'th_pnl_pct':        {'he': 'רווח/הפסד (%)',     'en': 'Profit/Loss (%)'},
    'th_weight':         {'he': 'משקל',              'en': 'Weight'},
    'empty_no_data':     {'he': 'אין נתונים. ייבא קובץ יומי כדי להתחיל:',
                          'en': 'No data available. Import a daily file to get started:'},

    # ── Transactions page ──
    'page_transactions':       {'he': 'כללי - יומן פעולות',    'en': 'General - Activity Log'},
    'add_deposit_title':       {'he': 'הוספת הפקדה',           'en': 'Add Deposit'},
    'label_amount':            {'he': 'סכום:',                 'en': 'Amount:'},
    'btn_add_deposit':         {'he': 'הוסף הפקדה',            'en': 'Add Deposit'},
    'transactions_title':      {'he': 'פעולות',                'en': 'Transactions'},
    'th_date':                 {'he': 'תאריך',                 'en': 'Date'},
    'th_action':               {'he': 'פעולה',                 'en': 'Action'},
    'th_amount':               {'he': 'סכום',                  'en': 'Amount'},
    'th_balance':              {'he': 'יתרה',                  'en': 'Balance'},
    'th_cost_change_pct':      {'he': 'שינוי מעלות (%)',       'en': 'Cost Change (%)'},
    'th_cost_change_ils':      {'he': 'שינוי מעלות (₪)',       'en': 'Cost Change (₪)'},
    'th_notes':                {'he': 'הערות',                 'en': 'Notes'},
    'summary_title':           {'he': 'סיכום',                 'en': 'Summary'},
    'summary_total_deposits':  {'he': 'סך הפקדות',             'en': 'Total Deposits'},
    'summary_deposits_for_calc': {'he': 'סך הפקדות לחישוב שינוי מעלות',
                                  'en': 'Total Deposits for Cost Change Calculation'},
    'summary_cost_change_ils': {'he': 'שינוי מעלות (₪)',       'en': 'Cost Change (₪)'},
    'summary_cost_change_pct': {'he': 'שינוי מעלות (%)',       'en': 'Cost Change (%)'},
    'summary_net_tax':         {'he': 'מס נטו לתשלום (25%)',   'en': 'Net Tax Payable (25%)'},

    # ── Daily summary page ──
    'page_daily_summary':   {'he': 'סיכום יומי',    'en': 'Daily Summary'},
    'th_morning_value':     {'he': 'שווי בוקר',     'en': 'Morning Value'},
    'th_current_value':     {'he': 'שווי נוכחי',    'en': 'Current Value'},
    'th_deposits':          {'he': 'הפקדות',        'en': 'Deposits'},
    'th_daily_pnl':         {'he': 'רווח/הפסד יומי', 'en': 'Daily Profit/Loss'},
    'th_change_pct':        {'he': 'שינוי (%)',      'en': 'Change (%)'},
    'th_best_stock':        {'he': 'מניה חזקה',     'en': 'Best Performing Stock'},
    'th_worst_stock':       {'he': 'מניה חלשה',     'en': 'Worst Performing Stock'},
    'empty_daily_summary':  {'he': 'אין נתוני סיכום יומי. ייבא קבצים יומיים כדי ליצור היסטוריה.',
                             'en': 'No daily summary data. Import daily files to build history.'},

    # ── Daily details page ──
    'page_daily_details':    {'he': 'יומי מלא - פירוט ניירות',  'en': 'Full Daily - Security Details'},
    'detail_title':          {'he': 'פירוט יומי לפי נייר',      'en': 'Daily Breakdown by Security'},
    'pivot_security_title':  {'he': 'סיכום לפי נייר',           'en': 'Summary by Security'},
    'pivot_date_title':      {'he': 'סיכום לפי תאריך',          'en': 'Summary by Date'},
    'th_tase_id':            {'he': 'מספר',                     'en': 'Number'},
    'th_change_ils':         {'he': 'שינוי (₪)',                'en': 'Change (₪)'},
    'th_change_pct_col':     {'he': 'שינוי (%)',                'en': 'Change (%)'},
    'th_total_change_ils':   {'he': 'סך שינוי (₪)',             'en': 'Total Change (₪)'},
    'th_max_ils':            {'he': 'מקס׳ (₪)',                 'en': 'Max (₪)'},
    'th_min_ils':            {'he': 'מינ׳ (₪)',                 'en': 'Min (₪)'},
    'th_total_change_pct':   {'he': 'סך שינוי (%)',             'en': 'Total Change (%)'},
    'th_max_pct':            {'he': 'מקס׳ (%)',                 'en': 'Max (%)'},
    'th_min_pct':            {'he': 'מינ׳ (%)',                 'en': 'Min (%)'},
    'th_securities_count':   {'he': 'ניירות',                   'en': 'Securities'},
    'total_label':           {'he': 'סך הכל',                   'en': 'Total'},
    'subtotal_prefix':       {'he': 'סה"כ',                     'en': 'Subtotal'},
    'empty_daily_details':   {'he': 'אין נתונים יומיים. ייבא קבצים יומיים כדי ליצור היסטוריה.',
                              'en': 'No daily data. Import daily files to build history.'},

    # ── Security type labels ──
    'type_stock':            {'he': 'מניות',        'en': 'Stocks'},
    'type_mutual_fund':      {'he': 'קרן',          'en': 'Fund'},
    'type_mutual_fund_long': {'he': 'קרנות נאמנות',  'en': 'Mutual Funds'},
    'type_etf':              {'he': 'תעודת סל',     'en': 'ETF'},
    'type_etf_long':         {'he': 'תעודות סל',    'en': 'ETFs'},
    'type_bond':             {'he': 'אג"ח',         'en': 'Bond'},
    'type_other':            {'he': 'אחר',          'en': 'Other'},

    # ── Trades page ──
    'page_trades':        {'he': 'עסקאות - קניות ומכירות',   'en': 'Trades - Buys and Sells'},
    'label_tax_year':     {'he': 'שנת מס:',                  'en': 'Tax Year:'},
    'all_time':           {'he': 'כל התקופה',                'en': 'All Time'},
    'stat_gains':         {'he': 'רווח ממכירות',              'en': 'Gains from Sales'},
    'stat_losses':        {'he': 'הפסד ממכירות',              'en': 'Losses from Sales'},
    'stat_net_balance':   {'he': 'יתרה נטו',                 'en': 'Net Balance'},
    'stat_loss_carryover': {'he': 'הפסד מועבר משנים קודמות',  'en': 'Loss Carryforward'},
    'stat_tax_on_gains':  {'he': 'מס על רווחים (25%)',        'en': 'Tax on Gains (25%)'},
    'stat_tax_offset':    {'he': 'קיזוז מס מהפסדים',         'en': 'Tax Offset from Losses'},
    'stat_net_tax':       {'he': 'מס נטו לתשלום',            'en': 'Net Tax Payable'},
    'trade_log_title':    {'he': 'יומן עסקאות',              'en': 'Trade Log'},
    'th_trade_action':    {'he': 'פעולה',                    'en': 'Action'},
    'th_trade_type':      {'he': 'סוג',                      'en': 'Type'},
    'th_quantity':        {'he': 'כמות',                     'en': 'Quantity'},
    'th_price_ils':       {'he': 'מחיר (₪)',                 'en': 'Price (₪)'},
    'th_amount_ils':      {'he': 'סכום (₪)',                 'en': 'Amount (₪)'},
    'badge_buy':          {'he': 'קניה',                     'en': 'Buy'},
    'badge_sell':         {'he': 'מכירה',                    'en': 'Sell'},
    'closed_title':       {'he': 'פוזיציות סגורות',           'en': 'Closed Positions'},
    'th_avg_buy':         {'he': 'עלות ממוצעת (₪)',           'en': 'Average Cost (₪)'},
    'th_avg_sell':        {'he': 'מחיר מכירה ממוצע (₪)',      'en': 'Average Sell Price (₪)'},
    'th_period':          {'he': 'תקופה',                    'en': 'Period'},
    'grand_total':        {'he': 'סה"כ',                     'en': 'Grand Total'},
    'empty_trades':       {'he': 'אין עסקאות. ייבא קבצי עסקאות כדי להתחיל:',
                           'en': 'No trades available. Import trade files to get started.'},

    # ── Transaction action labels (queries.py) ──
    'action_deposit':          {'he': 'הפקדה',          'en': 'Deposit'},
    'action_initial_transfer': {'he': 'העברה ראשונית',   'en': 'Initial Transfer'},
    'action_month_summary':    {'he': 'סיכום חודש',      'en': 'Monthly Summary'},

    # ── Flash messages (server.py) ──
    'flash_no_file':        {'he': 'לא נבחר קובץ',       'en': 'No file selected'},
    'flash_no_date':        {'he': 'לא הוזן תאריך',      'en': 'No date entered'},
    'flash_invalid_date':   {'he': 'תאריך לא תקין',      'en': 'Invalid date'},
    'flash_import_error':   {'he': 'שגיאה בייבוא',       'en': 'Import error'},
    'flash_no_amount':      {'he': 'לא הוזן סכום',       'en': 'No amount entered'},
    'flash_invalid_amount': {'he': 'סכום לא תקין',       'en': 'Invalid amount'},
    'flash_duplicate':      {'he': 'קובץ כבר יובא בעבר', 'en': 'File has already been imported'},
    'flash_import_success': {'he': 'יובאו {rows} שורות ({new} אחזקות חדשות) לתאריך {date}',
                             'en': 'Imported {rows} rows ({new} new holdings) for date {date}'},
    'flash_deposit_success': {'he': 'הפקדה בסך {amount} ₪ נוספה בהצלחה לתאריך {date}',
                              'en': 'Deposit of ₪{amount} was successfully added for date {date}'},
    'flash_deposit_error':  {'he': 'שגיאה בהוספת הפקדה',  'en': 'Error adding deposit'},
}


def get_translations(lang='he'):
    """Return a flat {key: string} dict for the given language."""
    return {k: v.get(lang, v['he']) for k, v in TRANSLATIONS.items()}


def get_translations_json(lang='he'):
    """Return translations as a JSON string for embedding in JavaScript."""
    return json.dumps(get_translations(lang), ensure_ascii=False)


def t(key, lang='he', **kwargs):
    """Get a single translated string, with optional format kwargs."""
    text = TRANSLATIONS.get(key, {}).get(lang, key)
    if kwargs:
        text = text.format(**kwargs)
    return text
