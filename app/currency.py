"""Per-portfolio display currency helpers (display-only — no FX conversion).

A portfolio's currency is a label: it picks the symbol shown in the UI and the
default for new entries. All amounts are assumed to already be in that currency.
"""

# Display symbol per ISO-4217 code. Codes without an entry fall back to the code.
_SYMBOLS = {
    'ILS': '₪',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'JPY': '¥',
    'CHF': 'CHF',
    'CAD': 'C$',
    'AUD': 'A$',
}

# Offered in the portfolio currency picker (code, English label).
SUPPORTED = [
    ('ILS', 'Israeli Shekel (₪)'),
    ('USD', 'US Dollar ($)'),
    ('EUR', 'Euro (€)'),
    ('GBP', 'British Pound (£)'),
    ('JPY', 'Japanese Yen (¥)'),
    ('CHF', 'Swiss Franc'),
    ('CAD', 'Canadian Dollar (C$)'),
    ('AUD', 'Australian Dollar (A$)'),
]

DEFAULT_CURRENCY = 'ILS'


def normalize_currency(code):
    """Normalize a currency code to a 3-letter uppercase string (default ILS)."""
    code = (code or '').strip().upper()
    return code or DEFAULT_CURRENCY


def currency_symbol(code):
    """Display symbol for a currency code; falls back to the code itself."""
    return _SYMBOLS.get(normalize_currency(code), normalize_currency(code))


def is_agorot(code):
    """Whether per-share prices for this currency are quoted in subunits (agorot).

    Only ILS/TASE quotes in agorot (1/100). Everything else uses main units.
    """
    return normalize_currency(code) == 'ILS'
