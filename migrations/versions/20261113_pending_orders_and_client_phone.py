"""add pending fulfillment status and client phone

Revision ID: 20261113_pending
Revises: 20261106_coupon
Create Date: 2026-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20261113_pending"
down_revision = "20261106_coupon"
branch_labels = None
depends_on = None


STATUS_CONSTRAINT = "ck_order_status_allowed"
PENDING_STATUS = "status IN ('Pending', 'Completed', 'Cancelled', 'Refunded')"
LEGACY_STATUS = "status IN ('Completed', 'Cancelled', 'Refunded')"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "order" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("order")}
    checks = {constraint.get("name") for constraint in inspector.get_check_constraints("order")}
    with op.batch_alter_table("order") as batch_op:
        if "customer_phone" not in columns:
            batch_op.add_column(sa.Column("customer_phone", sa.String(length=32), nullable=True))
        if STATUS_CONSTRAINT in checks:
            batch_op.drop_constraint(STATUS_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(STATUS_CONSTRAINT, PENDING_STATUS)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "order" not in inspector.get_table_names():
        return

    order_table = sa.table("order", sa.column("status", sa.String(length=20)))
    bind.execute(order_table.update().where(order_table.c.status == "Pending").values(status="Completed"))
    columns = {column["name"] for column in inspector.get_columns("order")}
    checks = {constraint.get("name") for constraint in inspector.get_check_constraints("order")}
    with op.batch_alter_table("order") as batch_op:
        if STATUS_CONSTRAINT in checks:
            batch_op.drop_constraint(STATUS_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(STATUS_CONSTRAINT, LEGACY_STATUS)
        if "customer_phone" in columns:
            batch_op.drop_column("customer_phone")
