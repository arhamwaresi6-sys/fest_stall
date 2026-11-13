from datetime import datetime, timezone
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin
from ..extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    google_picture_url = db.Column(db.String(2048), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="CASHIER", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('ROOT', 'PENDING', 'OWNER', 'MANAGER', 'CASHIER', 'STAFF')",
            name="ck_user_role_allowed",
        ),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active

    @is_active.setter
    def is_active(self, value):
        self.active = value



@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
        return user if user and user.active else None
    except (TypeError, ValueError):
        return None
