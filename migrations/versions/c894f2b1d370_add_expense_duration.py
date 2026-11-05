"""Add expense duration for daily cost recognition.

Revision ID: c894f2b1d370
Revises: e74b392a1f06
Create Date: 2026-11-05 07:49:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c894f2b1d370"
down_revision = "e74b392a1f06"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("expense") as batch_op:
        batch_op.add_column(
            sa.Column(
                "duration_days",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "ck_expense_duration_positive",
            "duration_days > 0",
        )


def downgrade():
    with op.batch_alter_table("expense") as batch_op:
        batch_op.drop_constraint(
            "ck_expense_duration_positive",
            type_="check",
        )
        batch_op.drop_column("duration_days")
