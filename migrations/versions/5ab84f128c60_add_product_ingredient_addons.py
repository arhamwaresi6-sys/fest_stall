"""Add ingredient inventory and product add-ons.

Revision ID: 5ab84f128c60
Revises: d1f6a0c9b32e
Create Date: 2026-11-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "5ab84f128c60"
down_revision = "d1f6a0c9b32e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingredient",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=12), nullable=False),
        sa.Column("stock", sa.Numeric(12, 3), nullable=False),
        sa.Column("min_stock", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stock >= 0", name="ck_ingredient_stock_nonnegative"),
        sa.CheckConstraint("min_stock >= 0", name="ck_ingredient_min_stock_nonnegative"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_ingredient_unit_cost_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingredient_name", "ingredient", ["name"], unique=True)
    op.create_index("ix_ingredient_active", "ingredient", ["active"], unique=False)

    op.create_table(
        "ingredient_transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("previous_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("quantity_changed", sa.Numeric(12, 3), nullable=False),
        sa.Column("new_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["order.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingredient_transaction_ingredient_id", "ingredient_transaction", ["ingredient_id"], unique=False)
    op.create_index("ix_ingredient_transaction_created_at", "ingredient_transaction", ["created_at"], unique=False)

    op.create_table(
        "product_addon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity_used", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("quantity_used > 0", name="ck_product_addon_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_product_addon_price_nonnegative"),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "ingredient_id", name="uq_product_addon_ingredient"),
    )
    op.create_index("ix_product_addon_product_id", "product_addon", ["product_id"], unique=False)
    op.create_index("ix_product_addon_ingredient_id", "product_addon", ["ingredient_id"], unique=False)

    op.create_table(
        "order_item_addon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=True),
        sa.Column("ingredient_name", sa.String(length=120), nullable=False),
        sa.Column("ingredient_unit", sa.String(length=12), nullable=False),
        sa.Column("quantity_per_product", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_item.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_item_addon_order_item_id", "order_item_addon", ["order_item_id"], unique=False)


def downgrade():
    op.drop_index("ix_order_item_addon_order_item_id", table_name="order_item_addon")
    op.drop_table("order_item_addon")
    op.drop_index("ix_product_addon_ingredient_id", table_name="product_addon")
    op.drop_index("ix_product_addon_product_id", table_name="product_addon")
    op.drop_table("product_addon")
    op.drop_index("ix_ingredient_transaction_created_at", table_name="ingredient_transaction")
    op.drop_index("ix_ingredient_transaction_ingredient_id", table_name="ingredient_transaction")
    op.drop_table("ingredient_transaction")
    op.drop_index("ix_ingredient_active", table_name="ingredient")
    op.drop_index("ix_ingredient_name", table_name="ingredient")
    op.drop_table("ingredient")
