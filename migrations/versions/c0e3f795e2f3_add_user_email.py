"""add user email

Revision ID: c0e3f795e2f3
Revises: bd90cbf14188
Create Date: 2026-11-04 23:26:49.328770

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0e3f795e2f3'
down_revision = 'bd90cbf14188'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "user" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    if "email" not in columns:
        op.add_column("user", sa.Column("email", sa.String(length=254), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("user")}
    if "ix_user_email" not in indexes:
        op.create_index("ix_user_email", "user", ["email"], unique=True)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "user" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("user")}
    if "ix_user_email" in indexes:
        op.drop_index("ix_user_email", table_name="user")
    columns = {column["name"] for column in inspector.get_columns("user")}
    if "email" in columns:
        op.drop_column("user", "email")
