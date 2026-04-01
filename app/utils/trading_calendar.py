"""TASE trading calendar: weekends + Israeli public holidays."""

from datetime import datetime, timedelta
from functools import lru_cache

import holidays as holidays_lib
from holidays.constants import PUBLIC, OPTIONAL

from app.utils.date_utils import is_tase_weekend

# Special TASE closures not covered by the holidays library
MANUAL_CLOSURES = {
    '2026-01-04',  # First Sunday under Mon-Fri schedule — TASE closed for transition
}

# Substrings of OPTIONAL holiday names that TASE fully closes for
_TASE_OPTIONAL_KEYWORDS = (
    'פורים',         # Purim
    'יום הזיכרון',   # Memorial Day (Yom HaZikaron)
    'תשעה באב',      # Tisha B'Av
)

# TASE closes on the eve (day before) of each PUBLIC holiday.
# This covers: Erev Pesach, Erev Shavuot, Erev Rosh Hashana,
# Erev Yom Kippur, Erev Sukkot, Erev Shmini Atzeret.


@lru_cache(maxsize=20)
def _il_public(year):
    return holidays_lib.IL(years=year, categories=(PUBLIC,))


@lru_cache(maxsize=20)
def _il_optional(year):
    return holidays_lib.IL(years=year, categories=(OPTIONAL,))


def is_tase_holiday(date_str):
    """Return True if TASE is closed due to a holiday on this date.

    Covers:
    - All Israeli PUBLIC holidays (Passover, Rosh Hashana, etc.)
    - Eves of PUBLIC holidays (TASE closes the day before each major holiday)
    - Selected OPTIONAL holidays: Purim, Memorial Day, Tisha B'Av
    - Manual closures (e.g. 2026-01-04 schedule transition)

    Args:
        date_str: ISO date string like "2026-04-01"

    Returns:
        True if TASE is closed due to a holiday
    """
    if date_str in MANUAL_CLOSURES:
        return True

    dt = datetime.strptime(date_str, '%Y-%m-%d').date()
    pub = _il_public(dt.year)

    # Check if this date is a public holiday
    if dt in pub:
        return True

    # Check if tomorrow is a public holiday (today is the eve — TASE closes)
    tomorrow = dt + timedelta(days=1)
    if tomorrow in _il_public(tomorrow.year):
        return True

    # Check selected optional holidays that TASE closes for
    opt_name = _il_optional(dt.year).get(dt, '')
    if opt_name and any(kw in opt_name for kw in _TASE_OPTIONAL_KEYWORDS):
        return True

    return False


def is_non_trading_day(date_str):
    """Return True if TASE is closed on this date (weekend or holiday).

    Args:
        date_str: ISO date string like "2026-04-01"

    Returns:
        True if TASE does not trade on this date
    """
    return is_tase_weekend(date_str) or is_tase_holiday(date_str)
