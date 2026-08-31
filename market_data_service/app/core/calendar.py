"""NSE market calendar — trading hours, session detection, holidays."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

settings = get_settings()
IST = ZoneInfo(settings.MARKET_TIMEZONE)

# NSE session boundaries
PREOPEN_START = time(9, 0)
MARKET_OPEN   = time(9, 15)
MARKET_CLOSE  = time(15, 30)

# NSE 2024-2025 exchange holidays (add more as needed)
# Source: NSE circulars
NSE_HOLIDAYS: frozenset[date] = frozenset([
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti / Good Friday
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali (Balipratipada)
    date(2025, 11, 5),   # Prakash Gurpurb Sri Guru Nanak Dev Ji
    date(2025, 12, 25),  # Christmas
])


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(dt: date | None = None) -> bool:
    d = dt or now_ist().date()
    if d.weekday() >= 5:        # Saturday / Sunday
        return False
    if d in NSE_HOLIDAYS:
        return False
    return True


def is_market_open(dt: datetime | None = None) -> bool:
    now = dt or now_ist()
    if not is_trading_day(now.date()):
        return False
    t = now.time().replace(second=0, microsecond=0)
    return MARKET_OPEN <= t < MARKET_CLOSE


def is_preopen(dt: datetime | None = None) -> bool:
    now = dt or now_ist()
    if not is_trading_day(now.date()):
        return False
    t = now.time().replace(second=0, microsecond=0)
    return PREOPEN_START <= t < MARKET_OPEN


def seconds_to_market_open(dt: datetime | None = None) -> float:
    """Seconds until next market open from now."""
    now = dt or now_ist()
    candidate = now.date()

    # Find next trading day
    for _ in range(10):
        if is_trading_day(candidate):
            open_dt = datetime.combine(candidate, MARKET_OPEN, tzinfo=IST)
            if open_dt > now:
                return (open_dt - now).total_seconds()
        candidate += timedelta(days=1)

    return float("inf")


def candle_start(ts: datetime, timeframe_minutes: int) -> datetime:
    """Align a timestamp to the start of its candle bucket."""
    # Normalise to seconds
    epoch = int(ts.timestamp())
    period = timeframe_minutes * 60
    aligned = (epoch // period) * period
    return datetime.fromtimestamp(aligned, tz=IST)


def candle_start_epoch(ts_epoch: int, timeframe_minutes: int) -> int:
    """Return epoch seconds of candle start — no datetime overhead."""
    period = timeframe_minutes * 60
    return (ts_epoch // period) * period
