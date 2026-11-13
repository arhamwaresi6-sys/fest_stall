"""save preferred payment method on orders"""
from alembic import op
import sqlalchemy as sa


revision = "20261113_paymethod"
down_revision = "20261113_google"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_order_payment_method_allowed"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "order" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("order")}
    checks = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("order")
    }
    with op.batch_alter_table("order") as batch_op:
        if "payment_method" not in columns:
            batch_op.add_column(
                sa.Column(
                    "payment_method",
                    sa.String(length=20),
                    nullable=False,
                    server_default="hand",
                )
            )
        if CONSTRAINT_NAME not in checks:
            batch_op.create_check_constraint(
                CONSTRAINT_NAME,
                "payment_method IN ('hand', 'bkash')",
            )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "order" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("order")}
    checks = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("order")
    }
    with op.batch_alter_table("order") as batch_op:
        if CONSTRAINT_NAME in checks:
            batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
        if "payment_method" in columns:
            batch_op.drop_column("payment_method")
