"""create_holdings_orders_trades_tables

Revision ID: 0a9d3e1ee45c
Revises: 458863d84def
Create Date: 2026-08-27 17:53:35.077011

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0a9d3e1ee45c"
down_revision: Union[str, Sequence[str], None] = "458863d84def"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create Holdings Table
    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_buy_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("cost_value", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=False),
        sa.Column("pnl_pct", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_holdings_id"), "holdings", ["id"], unique=False)
    op.create_index(
        op.f("ix_holdings_symbol_id"), "holdings", ["symbol_id"], unique=False
    )

    # 2. Create Orders Table
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=100), nullable=False),
        sa.Column("broker_order_id", sa.String(length=100), nullable=True),
        sa.Column(
            "side",
            sa.Enum("BUY", "SELL", name="orderside", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "MARKET", "LIMIT", "SL", "SL_M", name="ordertype", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "OPEN",
                "COMPLETE",
                "CANCELLED",
                "REJECTED",
                name="orderstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("trigger_price", sa.Float(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("status_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_orders_broker_order_id"), "orders", ["broker_order_id"], unique=False
    )
    op.create_index(op.f("ix_orders_id"), "orders", ["id"], unique=False)
    op.create_index(op.f("ix_orders_symbol_id"), "orders", ["symbol_id"], unique=False)

    # 3. Create Trades Table
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=100), nullable=False),
        sa.Column(
            "side",
            sa.Enum("BUY", "SELL", name="orderside", native_enum=False),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_date", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=50), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trades_id"), "trades", ["id"], unique=False)
    op.create_index(op.f("ix_trades_symbol_id"), "trades", ["symbol_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trades_symbol_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_id"), table_name="trades")
    op.drop_table("trades")

    op.drop_index(op.f("ix_orders_symbol_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_broker_order_id"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_holdings_symbol_id"), table_name="holdings")
    op.drop_index(op.f("ix_holdings_id"), table_name="holdings")
    op.drop_table("holdings")
