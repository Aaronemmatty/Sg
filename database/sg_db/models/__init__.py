"""Aggregate export of all ORM models for Alembic autogenerate."""

from sg_db.models.audit import AuditLog
from sg_db.models.identity import ApiKey, Permission, Role, RolePermission, User, UserRole
from sg_db.models.market_data import MarketBar
from sg_db.models.ml import MlModel, MlPrediction
from sg_db.models.notifications import Notification
from sg_db.models.portfolio import Portfolio, PortfolioSnapshot
from sg_db.models.risk import RiskEvent
from sg_db.models.signals import Signal
from sg_db.models.system import SystemEvent
from sg_db.models.tenant import Tenant
from sg_db.models.trading import Order, Position, Strategy, Trade

__all__ = [
    "Tenant",
    "User",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
    "ApiKey",
    "Strategy",
    "Order",
    "Trade",
    "Position",
    "Portfolio",
    "PortfolioSnapshot",
    "MarketBar",
    "Signal",
    "RiskEvent",
    "MlModel",
    "MlPrediction",
    "AuditLog",
    "SystemEvent",
    "Notification",
]
