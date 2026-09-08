import sqlalchemy as sa
from alembic import op

"""create_broker_balances_table

Revision ID: f32d9c769bc2
Revises: 5547767032c3
Create Date: 2026-09-02 17:37:10.339420

"""
"""create_broker_balances_table"""


# revision identifiers, used by Alembic.
revision = "f32d9c769bc2"
down_revision = "5547767032c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_balances",
        sa.Column("broker", sa.String(length=50), primary_key=True),
        sa.Column(
            "currency", sa.String(length=10), nullable=False, server_default="INR"
        ),
        sa.Column(
            "cash_available",
            sa.Numeric(precision=15, scale=2),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("broker_balances")
