"""create_market_data_all_view

Revision ID: 458863d84def
Revises: 18c94642806b
Create Date: 2026-08-05 13:26:09.025955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '458863d84def'
down_revision: Union[str, Sequence[str], None] = '18c94642806b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op

from alembic import op


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW market_data_all AS
        SELECT id, symbol_id, date, open, high, low, close, adj_close, volume
        FROM market_data_eod
        UNION ALL
        SELECT id, symbol_id, date, open, high, low, close, adj_close, volume
        FROM market_data_history;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS market_data_all;")
