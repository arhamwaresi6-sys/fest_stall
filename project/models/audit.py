from datetime import datetime, timezone
from ..extensions import db


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(80))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    user = db.relationship("User", backref="audit_events")
