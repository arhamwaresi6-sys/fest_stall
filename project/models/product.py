from datetime import datetime, timezone
from ..extensions import db


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text)
    category = db.Column(db.String(80), nullable=False, default="Other", index=True)
    selling_price = db.Column(db.Numeric(12, 2), nullable=False)
    cost_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    min_stock = db.Column(db.Integer, nullable=False, default=5)
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    image_filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.CheckConstraint("selling_price >= 0", name="ck_product_selling_nonnegative"),
                      db.CheckConstraint("cost_price >= 0", name="ck_product_cost_nonnegative"),
                      db.CheckConstraint("stock >= 0", name="ck_product_stock_nonnegative"))
