"""Cascade order and product dependent rows on deletion.

Revision ID: e74b392a1f06
Revises: 5ab84f128c60
Create Date: 2026-11-05 07:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "e74b392a1f06"
down_revision = "5ab84f128c60"
branch_labels = None
depends_on = None


FOREIGN_KEYS = (
    ("order_item", ("order_id",), "order", ("id",), "CASCADE"),
    ("order_item", ("product_id",), "product", ("id",), "SET NULL"),
    ("payment", ("order_id",), "order", ("id",), "CASCADE"),
    ("inventory_transaction", ("product_id",), "product", ("id",), "CASCADE"),
    ("inventory_transaction", ("order_id",), "order", ("id",), "CASCADE"),
    ("ingredient_transaction", ("order_id",), "order", ("id",), "CASCADE"),
    ("product_addon", ("product_id",), "product", ("id",), "CASCADE"),
    ("order_item_addon", ("order_item_id",), "order_item", ("id",), "CASCADE"),
)

FK_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _update_foreign_keys(ondelete):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    updates_by_table = {}

    for table, columns, referred_table, referred_columns, delete_action in FOREIGN_KEYS:
        if table not in tables:
            continue
        table_columns = {column["name"] for column in inspector.get_columns(table)}
        if not set(columns).issubset(table_columns):
            continue
        foreign_keys = inspector.get_foreign_keys(table)
        existing = next(
            (
                foreign_key
                for foreign_key in foreign_keys
                if foreign_key.get("constrained_columns") == list(columns)
                and foreign_key.get("referred_table") == referred_table
                and foreign_key.get("referred_columns") == list(referred_columns)
            ),
            None,
        )
        target_action = delete_action if ondelete else None
        existing_action = ((existing or {}).get("options") or {}).get("ondelete") or ""
        if existing and existing_action.upper() == (target_action or ""):
            continue
        constraint_name = (
            existing.get("name")
            if existing and existing.get("name")
            else f"fk_{table}_{columns[0]}_{referred_table}"
        )
        updates_by_table.setdefault(table, []).append(
            (constraint_name, existing, columns, referred_table, referred_columns, target_action)
        )

    for table, updates in updates_by_table.items():
        with op.batch_alter_table(
            table,
            naming_convention=FK_NAMING_CONVENTION,
        ) as batch_op:
            for name, existing, columns, referred_table, referred_columns, action in updates:
                if existing:
                    batch_op.drop_constraint(name, type_="foreignkey")
                batch_op.create_foreign_key(
                    name,
                    referred_table,
                    list(columns),
                    list(referred_columns),
                    ondelete=action,
                )


def upgrade():
    _update_foreign_keys(ondelete=True)


def downgrade():
    _update_foreign_keys(ondelete=False)
