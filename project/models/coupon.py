from datetime import datetime, timezone

from sqlalchemy.orm import validates

from ..extensions import db


class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    discount_type = db.Column(db.String(20), nullable=False)
    discount_value = db.Column(db.Numeric(12, 2), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    redeemed_at = db.Column(db.DateTime(timezone=True))
    redeemed_order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id", ondelete="SET NULL"),
        unique=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    __table_args__ = (
        db.CheckConstraint(
            "discount_type IN ('amount', 'percent')",
            name="ck_coupon_discount_type_allowed",
        ),
        db.CheckConstraint("discount_value > 0", name="ck_coupon_discount_value_positive"),
        db.CheckConstraint(
            "discount_type != 'percent' OR discount_value <= 100",
            name="ck_coupon_percent_max",
        ),
    )

    @validates("code")
    def normalize_code(self, key, value):
        return value.strip().upper()
