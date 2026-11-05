from datetime import datetime, timezone
from ..extensions import db


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="Miscellaneous", index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.Text)
    receipt_filename = db.Column(db.String(255))
    expense_date = db.Column(db.Date, nullable=False, index=True)
    duration_days = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = db.relationship("User", backref="expenses")
    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_expense_positive"),
        db.CheckConstraint("duration_days > 0", name="ck_expense_duration_positive"),
    )
