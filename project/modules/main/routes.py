from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from ...extensions import db
from ...image_uploads import save_image
from ...models import AuditLog, Expense, Order, OrderItem, Payment, Product, Setting
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, audit, net_order_item_amounts, selected_window

bp = Blueprint("main", __name__)


@bp.get("/uploads/<path:filename>")
@login_required
def private_upload(filename):
    if filename.startswith("receipts/") and current_user.role not in FINANCIAL_ROLES:
        abort(403)
    return send_from_directory(Path(current_app.instance_path) / "uploads", filename)


@bp.get("/")
def index():
    return redirect(url_for("main.dashboard")) if current_user.is_authenticated else redirect(url_for("auth.login"))


@bp.get("/dashboard")
@login_required
def dashboard():
    start_date, end_date, start, end = selected_window(1)
    today_local = datetime.now(ZoneInfo("Asia/Dhaka")).date()
    orders = db.session.scalars(select(Order).where(Order.created_at >= start, Order.created_at < end).order_by(Order.created_at.desc())).all()
    sale_orders = [o for o in orders if o.status == "Completed"]
    total_revenue = sum((o.total for o in sale_orders), Decimal("0.00"))
    total_cogs = sum((i.unit_cost * i.quantity for o in sale_orders for i in o.items), Decimal("0.00"))
    expense_rows = db.session.scalars(select(Expense).where(Expense.expense_date >= start_date, Expense.expense_date <= end_date)).all()
    expense_total = sum((e.amount for e in expense_rows), Decimal("0.00"))
    payments = db.session.scalars(select(Payment).join(Order).where(Payment.created_at >= start, Payment.created_at < end, Payment.status == "Recorded", Order.status == "Completed")).all()
    by_method = {key: sum((p.amount for p in payments if p.method == key), Decimal("0.00")) for key in PAYMENT_METHODS}
    largest_method = max(by_method.values(), default=Decimal("0.00"))
    method_percent = {key: int((amount / largest_method * 100).quantize(Decimal("1"))) if largest_method else 0 for key, amount in by_method.items()}
    item_totals = defaultdict(lambda: {"units": 0, "revenue": Decimal("0.00"), "cost": Decimal("0.00"), "orders": set()})
    for order in sale_orders:
        for item, net_line in zip(order.items, net_order_item_amounts(order)):
            row = item_totals[item.product_name]
            row["units"] += item.quantity
            row["cost"] += item.unit_cost * item.quantity
            row["orders"].add(order.id)
            row["revenue"] += net_line
    best_products = sorted(item_totals.items(), key=lambda entry: (entry[1]["revenue"] - entry[1]["cost"], entry[1]["units"]), reverse=True)
    span = (end_date - start_date).days + 1
    use_weeks = span > 31
    bucketed = defaultdict(lambda: {"sales": Decimal("0.00"), "expenses": Decimal("0.00")})
    zone = ZoneInfo("Asia/Dhaka")
    for order in sale_orders:
        local_day = order.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).date() if order.created_at.tzinfo is None else order.created_at.astimezone(zone).date()
        key = (local_day - timedelta(days=local_day.weekday())).isoformat() if use_weeks else local_day.isoformat()
        bucketed[key]["sales"] += order.total
    for expense in expense_rows:
        key = (expense.expense_date - timedelta(days=expense.expense_date.weekday())).isoformat() if use_weeks else expense.expense_date.isoformat()
        bucketed[key]["expenses"] += expense.amount
    if use_weeks:
        cursor = start_date - timedelta(days=start_date.weekday())
        last = end_date - timedelta(days=end_date.weekday())
        chart_keys = []
        while cursor <= last:
            chart_keys.append(cursor.isoformat())
            cursor += timedelta(days=7)
    else:
        chart_keys = [(start_date + timedelta(days=i)).isoformat() for i in range(span)]
    chart_labels = [key[5:] for key in chart_keys]
    chart_sales = [bucketed[key]["sales"] for key in chart_keys]
    chart_expenses = [bucketed[key]["expenses"] for key in chart_keys]
    products = db.session.scalars(select(Product).where(Product.is_archived.is_(False)).order_by(Product.name)).all()
    low_stock = [p for p in products if p.stock <= p.min_stock]
    recent_orders = db.session.scalars(select(Order).order_by(Order.created_at.desc()).limit(7)).all()
    audit_events = db.session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(6)).all() if current_user.role in FINANCIAL_ROLES else []
    return render_template("dashboard/index.html", start_date=start_date, end_date=end_date,
                           total_revenue=total_revenue, total_cogs=total_cogs, expense_total=expense_total,
                           net_profit=total_revenue-total_cogs-expense_total, order_count=len(sale_orders),
                           average_order=total_revenue/len(sale_orders) if sale_orders else Decimal("0.00"),
                           by_method=by_method, payment_names=PAYMENT_METHODS, products=products,
                           low_stock=low_stock, out_stock=sum(1 for p in products if p.stock == 0),
                           recent_orders=recent_orders, best_products=best_products[:8], audit_events=audit_events,
                           chart_labels=chart_labels, chart_sales=chart_sales, chart_expenses=chart_expenses,
                           chart_max=max(chart_sales + chart_expenses, default=Decimal("0.00")), chart_weekly=use_weeks,
                           method_percent=method_percent, today_local=today_local,
                           yesterday_local=today_local-timedelta(days=1), week_start=today_local-timedelta(days=6))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if current_user.role not in {"ROOT", "OWNER"}:
        abort(403)
    keys = ["stall_name", "contact_info", "receipt_footer", "currency", "festival_open", "festival_close", "low_stock_threshold"]
    if request.method == "POST":
        try:
            threshold = int(request.form.get("low_stock_threshold", "5"))
            if threshold < 0 or threshold > 100000:
                raise ValueError
        except ValueError:
            flash("Low-stock threshold must be a whole number between 0 and 100,000.", "danger")
            return redirect(url_for("main.settings"))
        for key in keys:
            row = db.session.get(Setting, key) or Setting(key=key, value="")
            row.value = str(threshold) if key == "low_stock_threshold" else request.form.get(key, "").strip()[:300]
            db.session.add(row)
        try:
            logo_filename = save_image(request.files.get("logo"), "logos")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("main.settings"))
        if logo_filename:
            logo = db.session.get(Setting, "logo_filename") or Setting(key="logo_filename", value="")
            logo.value = logo_filename
            db.session.add(logo)
        audit("Updated stall settings", "Setting")
        db.session.commit()
        flash("Stall settings saved.", "success")
        return redirect(url_for("main.settings"))
    values = {key: (db.session.get(Setting, key).value if db.session.get(Setting, key) else "") for key in keys}
    logo = db.session.get(Setting, "logo_filename")
    values["logo_filename"] = logo.value if logo else ""
    return render_template("settings/index.html", values=values)


@bp.app_context_processor
def inject_stall_name():
    keys = ("stall_name", "contact_info", "receipt_footer", "currency", "logo_filename")
    values = {
        row.key: row.value
        for row in db.session.scalars(select(Setting).where(Setting.key.in_(keys)))
    }
    return {
        "stall_name": values.get("stall_name") or "Festival Bites",
        "stall_contact": values.get("contact_info", ""),
        "receipt_footer": values.get("receipt_footer", ""),
        "stall_logo": values.get("logo_filename", ""),
        "currency_symbol": values.get("currency", "").strip() or "৳",
    }
