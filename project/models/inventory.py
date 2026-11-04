from datetime import datetime, timezone
from ..extensions import db


class InventoryTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    previous_quantity = db.Column(db.Integer, nullable=False)
    quantity_changed = db.Column(db.Integer, nullable=False)
    new_quantity = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(30), nullable=False, default="Adjustment")
    reason = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    product = db.relationship("Product", backref="inventory_transactions")
    user = db.relationship("User", backref="inventory_transactions")
