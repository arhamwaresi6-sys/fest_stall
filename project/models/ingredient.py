from datetime import datetime, timezone

from ..extensions import db


class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    unit = db.Column(db.String(12), nullable=False)
    stock = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    min_stock = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    unit_cost = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    __table_args__ = (
        db.CheckConstraint("stock >= 0", name="ck_ingredient_stock_nonnegative"),
        db.CheckConstraint("min_stock >= 0", name="ck_ingredient_min_stock_nonnegative"),
        db.CheckConstraint("unit_cost >= 0", name="ck_ingredient_unit_cost_nonnegative"),
    )


class IngredientTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(
        db.Integer, db.ForeignKey("ingredient.id"), nullable=False, index=True
    )
    previous_quantity = db.Column(db.Numeric(12, 3), nullable=False)
    quantity_changed = db.Column(db.Numeric(12, 3), nullable=False)
    new_quantity = db.Column(db.Numeric(12, 3), nullable=False)
    kind = db.Column(db.String(30), nullable=False, default="Adjustment")
    reason = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"))
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    ingredient = db.relationship("Ingredient", backref="transactions")
    user = db.relationship("User", backref="ingredient_transactions")


class ProductAddon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id = db.Column(
        db.Integer, db.ForeignKey("ingredient.id"), nullable=False, index=True
    )
    quantity_used = db.Column(db.Numeric(12, 3), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    product = db.relationship("Product", back_populates="addons")
    ingredient = db.relationship("Ingredient")
    __table_args__ = (
        db.UniqueConstraint("product_id", "ingredient_id", name="uq_product_addon_ingredient"),
        db.CheckConstraint("quantity_used > 0", name="ck_product_addon_quantity_positive"),
        db.CheckConstraint("unit_price >= 0", name="ck_product_addon_price_nonnegative"),
    )


class OrderItemAddon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(
        db.Integer, db.ForeignKey("order_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id = db.Column(
        db.Integer, db.ForeignKey("ingredient.id", ondelete="SET NULL"), nullable=True
    )
    ingredient_name = db.Column(db.String(120), nullable=False)
    ingredient_unit = db.Column(db.String(12), nullable=False)
    quantity_per_product = db.Column(db.Numeric(12, 3), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 4), nullable=False)
    order_item = db.relationship("OrderItem", back_populates="addons")
    ingredient = db.relationship("Ingredient")
