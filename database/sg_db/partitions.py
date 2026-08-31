"""Helpers for creating monthly RANGE partitions."""

from datetime import date

import sqlalchemy as sa
from alembic import op


PARTITIONED_TABLES: dict[str, str] = {
    "orders": "created_at",
    "trades": "executed_at",
    "portfolio_snapshots": "snapshot_at",
    "market_bars": "bar_ts",
    "signals": "created_at",
    "risk_events": "created_at",
    "ml_predictions": "predicted_at",
    "audit_logs": "created_at",
    "system_events": "created_at",
}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return [start, end) date bounds for a calendar month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_{year}_{month:02d}"


def create_monthly_partitions(
    table: str,
    column: str,
    start_year: int,
    start_month: int,
    months: int,
) -> None:
    """Create monthly RANGE partitions for a partitioned parent table."""
    year, month = start_year, start_month
    for _ in range(months):
        start, end = month_bounds(year, month)
        name = partition_name(table, year, month)
        op.execute(
            sa.text(
                f"""
                CREATE TABLE IF NOT EXISTS {name}
                PARTITION OF {table}
                FOR VALUES FROM (TIMESTAMPTZ '{start.isoformat()} 00:00:00+00')
                TO (TIMESTAMPTZ '{end.isoformat()} 00:00:00+00');
                """
            )
        )
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def create_all_partitions(start_year: int = 2026, months: int = 24) -> None:
    """Bootstrap partitions for all high-volume tables."""
    for table, column in PARTITIONED_TABLES.items():
        create_monthly_partitions(table, column, start_year, 1, months)
