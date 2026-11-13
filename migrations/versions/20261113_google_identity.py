"""add Google identity fields to users

Revision ID: 20261113_google
Revises: 20261113_pending
Create Date: 2026-11-13 19:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20261113_google"
down_revision = "20261113_pending"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "user" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    indexes = {index["name"] for index in inspector.get_indexes("user")}
    if "google_sub" not in columns:
        op.add_column("user", sa.Column("google_sub", sa.String(length=255), nullable=True))
    if "google_picture_url" not in columns:
        op.add_column("user", sa.Column("google_picture_url", sa.String(length=2048), nullable=True))
    if "ix_user_google_sub" not in indexes:
        op.create_index("ix_user_google_sub", "user", ["google_sub"], unique=True)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "user" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    indexes = {index["name"] for index in inspector.get_indexes("user")}
    if "ix_user_google_sub" in indexes:
        op.drop_index("ix_user_google_sub", table_name="user")
    if "google_picture_url" in columns:
        op.drop_column("user", "google_picture_url")
    if "google_sub" in columns:
        op.drop_column("user", "google_sub")
