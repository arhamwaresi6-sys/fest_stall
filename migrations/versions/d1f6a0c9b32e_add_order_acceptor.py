"""add order acceptor

Revision ID: d1f6a0c9b32e
Revises: c0e3f795e2f3
Create Date: 2026-11-05 00:59:40.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1f6a0c9b32e"
down_revision = "c0e3f795e2f3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "order" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("order")}
    if "accepted_by_id" in columns:
        return

    with op.batch_alter_table("order") as batch_op:
        batch_op.add_column(sa.Column("accepted_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_order_accepted_by_user",
            "user",
            ["accepted_by_id"],
            ["id"],
        )
    order_table = sa.table(
        "order",
        sa.column("accepted_by_id", sa.Integer()),
        sa.column("created_by_id", sa.Integer()),
    )
    bind.execute(
        order_table.update()
        .where(order_table.c.accepted_by_id.is_(None))
        .values(accepted_by_id=order_table.c.created_by_id)
    )
    with op.batch_alter_table("order") as batch_op:
        batch_op.alter_column(
            "accepted_by_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "order" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("order")}
    if "accepted_by_id" in columns:
        with op.batch_alter_table("order") as batch_op:
            batch_op.drop_column("accepted_by_id")
