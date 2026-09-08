"""add_unique_constraints_to_holdings_and_orders

Revision ID: 5547767032c3
Revises: d19e48aded2b
Create Date: 2026-08-31 18:51:02.936498

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5547767032c3"
down_revision: Union[str, Sequence[str], None] = "d19e48aded2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Clean up duplicate holdings (keep newest row per symbol+broker+strategy)
    op.execute("""
        DELETE FROM holdings a
        USING holdings b
        WHERE a.id < b.id
          AND a.symbol_id = b.symbol_id
          AND a.broker = b.broker
          AND a.strategy = b.strategy;
    """)

    # 2. Clean up duplicate orders if any
    op.execute("""
        DELETE FROM orders a
        USING orders b
        WHERE a.id < b.id
          AND a.broker_order_id = b.broker_order_id
          AND a.broker_order_id IS NOT NULL;
    """)

    # 3. Create Unique Constraints & Indexes
    op.create_unique_constraint(
        "uq_holdings_symbol_broker_strategy",
        "holdings",
        ["symbol_id", "broker", "strategy"],
    )
    op.drop_index(op.f("ix_orders_broker_order_id"), table_name="orders")
    op.create_index(
        op.f("ix_orders_broker_order_id"), "orders", ["broker_order_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_orders_broker_order_id"), table_name="orders")
    op.create_index(
        op.f("ix_orders_broker_order_id"), "orders", ["broker_order_id"], unique=False
    )
    op.drop_constraint("uq_holdings_symbol_broker_strategy", "holdings", type_="unique")
