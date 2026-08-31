"""Custom SQLAlchemy column types."""

from sqlalchemy import Numeric

# Financial precision: 18 digits total, 8 decimal places.
MONEY = Numeric(18, 8)
QUANTITY = Numeric(18, 8)
PRICE = Numeric(18, 8)
PERCENTAGE = Numeric(8, 4)
