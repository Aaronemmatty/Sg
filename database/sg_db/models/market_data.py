"""Market data storage — OHLCV bars partitioned by timestamp."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column

from sg_db.base import Base
from sg_db.enums import Timeframe
from sg_db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from sg_db.types import PRICE, QUANTITY


class MarketBar(Base, TimestampMixin):
    """Normalized OHLCV bar — shared across tenants, partitioned monthly."""

    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "timeframe", "bar_ts", name="uq_market_bars_symbol_tf_ts"),
        Index("ix_market_bars_symbol_tf_ts", "symbol", "timeframe", "bar_ts"),
        Index("ix_market_bars_exchange_symbol", "exchange", "symbol", "bar_ts"),
        {"postgresql_partition_by": "RANGE (bar_ts)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    bar_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[Timeframe] = mapped_column(
        Enum(Timeframe, name="timeframe", native_enum=False),
        nullable=False,
    )
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=0)
    vwap: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    trade_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
