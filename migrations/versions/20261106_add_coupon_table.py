"""create single-use coupon table

Revision ID: 20261106_coupon
Revises: c894f2b1d370
Create Date: 2026-11-06 18:31:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20261106_coupon"
down_revision = "c894f2b1d370"
branch_labels = None
depends_on = None


def upgrade():
    if "coupon" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "coupon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("discount_type", sa.String(length=20), nullable=False),
        sa.Column("discount_value", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_order_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "discount_type IN ('amount', 'percent')",
            name="ck_coupon_discount_type_allowed",
        ),
        sa.CheckConstraint(
            "discount_value > 0",
            name="ck_coupon_discount_value_positive",
        ),
        sa.CheckConstraint(
            "discount_type != 'percent' OR discount_value <= 100",
            name="ck_coupon_percent_max",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_order_id"], ["order.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("redeemed_order_id"),
    )
    op.create_index("ix_coupon_code", "coupon", ["code"], unique=False)


def downgrade():
    if "coupon" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_coupon_code", table_name="coupon")
    op.drop_table("coupon")
