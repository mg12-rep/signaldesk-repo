import enum
from datetime import datetime

from app.db.session import Base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship


# Enums
class AssetClass(str, enum.Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"

class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL_M"

class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# Exchanges & Symbols
class Exchange(Base):
    __tablename__ = "exchanges"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)  # NSE, NYSE, NASDAQ, TSX
    name = Column(String(100), nullable=False)
    country = Column(String(50), nullable=False)           # IN, US, CA
    timezone = Column(String(50), default="UTC")

    symbols = relationship("Symbol", back_populates="exchange_rel")


class Symbol(Base):
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True, index=True)
    trading_symbol = Column(String(30), nullable=False, index=True) # e.g. RELIANCE, AAPL, SHOP
    yf_symbol = Column(String(30), nullable=True)                  # e.g. RELIANCE.NS, SHOP.TO
    name = Column(String(200), nullable=True)
    
    exchange_id = Column(Integer, ForeignKey("exchanges.id"), nullable=False)
    instrument_token = Column(Integer, nullable=True)              # Broker token
    
    asset_class = Column(Enum(AssetClass, native_enum=False), default=AssetClass.EQUITY, nullable=False)
    is_index = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    exchange_rel = relationship("Exchange", back_populates="symbols")
    eod_data = relationship("MarketDataEOD", back_populates="symbol", cascade="all, delete-orphan")
    history_data = relationship("MarketDataHistory", back_populates="symbol", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('trading_symbol', 'exchange_id', name='_symbol_exchange_uc'),
    )


class IndexConstituent(Base):
    """Junction table for index membership (e.g., RELIANCE -> NIFTY 50 AND NIFTY 500)."""
    __tablename__ = "index_constituents"

    id = Column(Integer, primary_key=True, index=True)
    index_symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False)
    stock_symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False)
    weight = Column(Float, nullable=True)  # Percentage weight if available

    __table_args__ = (
        UniqueConstraint('index_symbol_id', 'stock_symbol_id', name='_index_stock_uc'),
    )


# Market Data Tables (Hot vs Cold Split)
class MarketDataEOD(Base):
    """HOT DATA: Stores recent 2 years of daily candles for live screeners and active alerts."""
    __tablename__ = "market_data_eod"

    id = Column(Integer, primary_key=True, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    adj_close = Column(Float, nullable=True)
    volume = Column(Integer, nullable=False)

    symbol = relationship("Symbol", back_populates="eod_data")

    __table_args__ = (
        UniqueConstraint('symbol_id', 'date', name='_symbol_date_eod_uc'),
        Index('idx_eod_symbol_date', 'symbol_id', 'date'),
    )


class MarketDataHistory(Base):
    """COLD DATA: Stores historical daily candles (> 2 years old) for strategy backtesting."""
    __tablename__ = "market_data_history"

    id = Column(Integer, primary_key=True, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    adj_close = Column(Float, nullable=True)
    volume = Column(Integer, nullable=False)

    symbol = relationship("Symbol", back_populates="history_data")

    __table_args__ = (
        UniqueConstraint('symbol_id', 'date', name='_symbol_date_history_uc'),
        Index('idx_history_symbol_date', 'symbol_id', 'date'),
    )


# Orders & Positions
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    
    broker_order_id = Column(String(100), nullable=True, index=True)
    side = Column(Enum(OrderSide, native_enum=False), nullable=False)
    order_type = Column(Enum(OrderType, native_enum=False), default=OrderType.MARKET, nullable=False)
    status = Column(Enum(OrderStatus, native_enum=False), default=OrderStatus.PENDING, nullable=False)
    
    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, default=0, nullable=False)
    
    price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)
    average_price = Column(Float, nullable=True)
    
    status_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    symbol = relationship("Symbol")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    
    stop_loss = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    
    status = Column(Enum(PositionStatus, native_enum=False), default=PositionStatus.OPEN, nullable=False)
    opened_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at = Column(DateTime, nullable=True)

    symbol = relationship("Symbol")