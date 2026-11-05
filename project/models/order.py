from datetime import datetime, timezone
from ..extensions import db


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    checkout_token = db.Column(db.String(64), unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="Completed", index=True)
    payment_status = db.Column(db.String(20), nullable=False, default="Unpaid", index=True)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    customer_name = db.Column(db.String(120))
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    cancellation_reason = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    accepted_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_order_accepted_by_user"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id], backref="orders")
    accepted_by = db.relationship("User", foreign_keys=[accepted_by_id], backref="accepted_orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="order", cascade="all, delete-orphan")
    __table_args__ = (db.CheckConstraint("status IN ('Completed', 'Cancelled', 'Refunded')", name="ck_order_status_allowed"),
                      db.CheckConstraint("payment_status IN ('Paid', 'Partially paid', 'Unpaid', 'Refunded')", name="ck_order_payment_status_allowed"))


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    product_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")
    addons = db.relationship("OrderItemAddon", back_populates="order_item", cascade="all, delete-orphan")
    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),)
