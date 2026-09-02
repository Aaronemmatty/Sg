"""NSE market calendar — trading hours, session detection, holidays."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# NSE Market Timezone
MARKET_TIMEZONE_NAME = "Asia/Kolkata"
IST = ZoneInfo(MARKET_TIMEZONE_NAME)

# NSE session boundaries (IST)
PREOPEN_START = time(9, 0)
MARKET_OPEN   = time(9, 15)
MARKET_CLOSE  = time(15, 30)

# NSE exchange trading holidays (2024 - 2026)
# Source: NSE official holiday circulars
NSE_HOLIDAYS: frozenset[date] = frozenset([
    # 2024
    date(2024, 1, 22),   # Special Holiday
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 8),    # Mahashivratri
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 11),   # Id-Ul-Fitr
    date(2024, 4, 17),   # Shri Ram Navami
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 20),   # Parliamentary Elections
    date(2024, 6, 17),   # Bakrid / Eid-Ul-Adha
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 10, 2),   # Mahatma Gandhi Jayanti
    date(2024, 11, 1),   # Diwali Laxmi Pujan
    date(2024, 11, 15),  # Gurunanak Jayanti
    date(2024, 11, 20),  # Maharashtra Assembly General Election
    date(2024, 12, 25),  # Christmas

    # 2025
    date(2025, 1, 26),   # Republic Day (Sunday)
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali (Balipratipada)
    date(2025, 11, 5),   # Prakash Gurpurb Sri Guru Nanak Dev Ji
    date(2025, 12, 25),  # Christmas

    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 16),   # Mahashivratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr
    date(2026, 3, 27),   # Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakrid / Eid ul-Adha
    date(2026, 8, 15),   # Independence Day (Saturday)
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali (Balipratipada)
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
])


def now_ist() -> datetime:
    """Return the current time in IST (Asia/Kolkata)."""
    return datetime.now(IST)


def ensure_ist(dt: datetime | date | None = None) -> datetime:
    """Ensure a given datetime is aware and in IST."""
    if dt is None:
        return now_ist()
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Naive datetimes are assumed to be IST
            return dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    # If a date object was passed, convert to start of day in IST
    return datetime.combine(dt, time(0, 0), tzinfo=IST)


def is_trading_day(dt: datetime | date | None = None) -> bool:
    """
    Check if the given date is an active NSE equity trading day (Monday–Friday, non-holiday).
    """
    if dt is None:
        d = now_ist().date()
    elif isinstance(dt, datetime):
        d = ensure_ist(dt).date()
    else:
        d = dt

    # Saturday (5) or Sunday (6)
    if d.weekday() >= 5:
        return False

    # NSE Holiday
    if d in NSE_HOLIDAYS:
        return False

    return True


def is_market_open(dt: datetime | None = None) -> bool:
    """
    Check if the NSE equity market is currently open for continuous trading (09:15:00 to 15:30:00 IST).
    Boundary semantics:
      - 09:15:00 IST is ALLOWED (open)
      - 15:30:00 IST is ALLOWED (closing bar / boundary)
      - 15:30:01+ / 15:31:00 IST is REJECTED (closed)
    """
    now = ensure_ist(dt)
    if not is_trading_day(now):
        return False

    t = now.time()
    # Continuous session from 09:15:00 up to 15:30:00 inclusive
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_preopen(dt: datetime | None = None) -> bool:
    """Check if the NSE equity market is in pre-open session (09:00:00 to 09:14:59 IST)."""
    now = ensure_ist(dt)
    if not is_trading_day(now):
        return False

    t = now.time()
    return PREOPEN_START <= t < MARKET_OPEN


def seconds_to_market_open(dt: datetime | None = None) -> float:
    """Return seconds from now (or specified dt) until next NSE market open."""
    now = ensure_ist(dt)
    candidate = now.date()

    for _ in range(15):
        if is_trading_day(candidate):
            open_dt = datetime.combine(candidate, MARKET_OPEN, tzinfo=IST)
            if open_dt > now:
                return (open_dt - now).total_seconds()
        candidate += timedelta(days=1)

    return float("inf")


def candle_start(ts: datetime, timeframe_minutes: int) -> datetime:
    """Align a timestamp to the start of its candle bucket in IST."""
    ts_ist = ensure_ist(ts)
    epoch = int(ts_ist.timestamp())
    period = timeframe_minutes * 60
    aligned = (epoch // period) * period
    return datetime.fromtimestamp(aligned, tz=IST)


def candle_start_epoch(ts_epoch: int, timeframe_minutes: int) -> int:
    """Return epoch seconds of candle start — no datetime overhead."""
    period = timeframe_minutes * 60
    return (ts_epoch // period) * period
