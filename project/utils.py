from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from zoneinfo import ZoneInfo

from flask import abort, request
from flask_login import current_user

from .extensions import db
from .models import AuditLog

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PAYMENT_METHODS = {"hand": "By hand (cash)", "bkash": "bKash"}
FINANCIAL_ROLES = {"ROOT", "OWNER", "MANAGER"}
PRODUCT_ROLES = {"ROOT", "OWNER", "MANAGER"}
STAFF_ROLES = {"ROOT", "OWNER", "MANAGER", "CASHIER", "STAFF"}


def decimal_value(value, field="amount", minimum=ZERO):
    try:
        number = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {field}.")
    if not number.is_finite() or number < minimum:
        raise ValueError(f"{field.title()} must be at least {minimum}.")
    return number


def quantity_value(value, field="quantity", minimum=Decimal("0")):
    try:
        number = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {field}.")
    if not number.is_finite():
        raise ValueError(f"Enter a valid {field}.")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field.title()} must be at least {minimum}.")
    return number


def cost_value(value, field="unit cost"):
    try:
        raw_number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {field}.")
    if not raw_number.is_finite():
        raise ValueError(f"Enter a valid {field}.")
    if raw_number < ZERO:
        raise ValueError(f"{field.title()} cannot be negative.")
    try:
        number = raw_number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"Enter a valid {field}.")
    return number


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role != "ROOT" and current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def audit(action, entity_type, entity_id=None, details=""):
    if current_user.is_authenticated:
        db.session.add(AuditLog(user_id=current_user.id, action=action, entity_type=entity_type,
                                entity_id=str(entity_id) if entity_id is not None else None,
                                details=(details or "")[:2000]))


def parse_date(value, fallback):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else fallback
    except ValueError:
        return fallback


def date_window(start_date, end_date):
    tz = ZoneInfo("Asia/Dhaka")
    start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end


def selected_window(default_days=1):
    today = datetime.now(ZoneInfo("Asia/Dhaka")).date()
    end_date = parse_date(request.args.get("end"), today)
    start_date = parse_date(request.args.get("start"), today - timedelta(days=default_days - 1))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date, *date_window(start_date, end_date)


def order_payment_status(order):
    received = sum((p.amount for p in order.payments if p.status == "Recorded"), ZERO)
    if order.status == "Refunded":
        return "Refunded"
    if received <= ZERO:
        return "Unpaid"
    if received >= order.total:
        return "Paid"
    return "Partially paid"


def refresh_order_payment_status(order):
    order.payment_status = order_payment_status(order)


def net_order_item_amounts(order):
    """Allocate an order-level discount across its saved item totals to the cent."""
    items = list(order.items)
    if not items:
        return []
    subtotal = order.subtotal or ZERO
    allocated = ZERO
    amounts = []
    for index, item in enumerate(items):
        if index == len(items) - 1:
            amount = order.total - allocated
        else:
            amount = ((item.line_total / subtotal) * order.total).quantize(CENT, rounding=ROUND_HALF_UP) if subtotal else ZERO
            allocated += amount
        amounts.append(amount)
    return amounts


def order_item_cost(item):
    addon_cost = sum(
        (addon.quantity_per_product * addon.unit_cost * item.quantity for addon in item.addons),
        ZERO,
    )
    return item.unit_cost * item.quantity + addon_cost
