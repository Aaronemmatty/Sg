"""PostgreSQL ENUM types shared across domain models."""

import enum


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    CHURNED = "churned"


class TradingMode(str, enum.Enum):
    LIVE = "live"
    PAPER = "paper"


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class StrategyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class SignalType(str, enum.Enum):
    ENTRY = "entry"
    EXIT = "exit"
    ADJUST = "adjust"
    HOLD = "hold"


class SignalSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


class RiskSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKING = "blocking"


class RiskEventType(str, enum.Enum):
    PRE_TRADE_REJECT = "pre_trade_reject"
    LIMIT_BREACH = "limit_breach"
    EXPOSURE_BREACH = "exposure_breach"
    DRAWDOWN_BREACH = "drawdown_breach"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    KILL_SWITCH_RELEASED = "kill_switch_released"
    POSITION_LIMIT = "position_limit"
    CONCENTRATION_LIMIT = "concentration_limit"


class ModelStatus(str, enum.Enum):
    TRAINING = "training"
    STAGING = "staging"
    PRODUCTION = "production"
    RETIRED = "retired"
    FAILED = "failed"


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    PUSH = "push"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"


class SystemEventSeverity(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditActorType(str, enum.Enum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"
    SERVICE = "service"


class Timeframe(str, enum.Enum):
    TICK = "tick"
    S1 = "1s"
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
