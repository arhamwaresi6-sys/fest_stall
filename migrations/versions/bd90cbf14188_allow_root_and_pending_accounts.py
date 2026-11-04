"""allow root and pending accounts

Revision ID: bd90cbf14188
Revises:
Create Date: 2026-11-04 23:03:32.662513

"""
from alembic import op
from alembic import context
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd90cbf14188'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        if context.get_context().dialect.name == "sqlite":
            raise RuntimeError("Offline migration SQL is not supported for SQLite; run flask db upgrade.")
        op.drop_constraint("ck_user_role_allowed", "user", type_="check")
        op.create_check_constraint(
            "ck_user_role_allowed",
            "user",
            "role IN ('ROOT', 'PENDING', 'OWNER', 'MANAGER', 'CASHIER', 'STAFF')",
        )
        return
    bind = op.get_bind()
    if "user" not in inspect(bind).get_table_names():
        return
    checks = inspect(bind).get_check_constraints("user")
    role_check = next((check for check in checks if check["name"] == "ck_user_role_allowed"), None)
    if role_check and "ROOT" in role_check["sqltext"] and "PENDING" in role_check["sqltext"]:
        return
    with op.batch_alter_table("user") as batch:
        if role_check:
            batch.drop_constraint("ck_user_role_allowed", type_="check")
        batch.create_check_constraint(
            "ck_user_role_allowed",
            "role IN ('ROOT', 'PENDING', 'OWNER', 'MANAGER', 'CASHIER', 'STAFF')",
        )


def downgrade():
    if context.is_offline_mode():
        op.execute(sa.text("UPDATE user SET role = 'OWNER' WHERE role = 'ROOT'"))
        op.execute(sa.text("UPDATE user SET role = 'STAFF', active = 0 WHERE role = 'PENDING'"))
        op.drop_constraint("ck_user_role_allowed", "user", type_="check")
        op.create_check_constraint(
            "ck_user_role_allowed",
            "user",
            "role IN ('OWNER', 'MANAGER', 'CASHIER', 'STAFF')",
        )
        return
    bind = op.get_bind()
    if "user" not in inspect(bind).get_table_names():
        return
    checks = inspect(bind).get_check_constraints("user")
    role_check = next((check for check in checks if check["name"] == "ck_user_role_allowed"), None)
    if role_check and ("ROOT" in role_check["sqltext"] or "PENDING" in role_check["sqltext"]):
        bind.execute(sa.text("UPDATE user SET role = 'OWNER' WHERE role = 'ROOT'"))
        bind.execute(sa.text("UPDATE user SET role = 'STAFF', active = 0 WHERE role = 'PENDING'"))
        with op.batch_alter_table("user") as batch:
            batch.drop_constraint("ck_user_role_allowed", type_="check")
            batch.create_check_constraint(
                "ck_user_role_allowed",
                "role IN ('OWNER', 'MANAGER', 'CASHIER', 'STAFF')",
            )
