from datetime import datetime, timezone
from ..extensions import db


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Recorded", index=True)
    reference_id = db.Column(db.String(120))
    notes = db.Column(db.Text)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    order = db.relationship("Order", back_populates="payments")
    recorded_by = db.relationship("User", backref="payments_recorded")
    __table_args__ = (db.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
                      db.CheckConstraint("method IN ('hand', 'bkash')", name="ck_payment_method_allowed"),
                      db.CheckConstraint("status IN ('Recorded', 'Refunded', 'Voided')", name="ck_payment_status_allowed"))
