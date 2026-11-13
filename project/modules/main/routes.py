from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from ...extensions import db
from ...models import AuditLog, Expense, Order, OrderItem, Payment, Product, Setting
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, audit, expense_amount_between, expense_amount_remaining, lifetime_sales_totals, net_order_item_amounts, order_item_cost, selected_window

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
    orders = db.session.scalars(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.addons))
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.created_at.desc())
    ).all()
    sale_orders = [o for o in orders if o.status == "Completed"]
    total_revenue = sum((o.total for o in sale_orders), Decimal("0.00"))
    total_cogs = sum((order_item_cost(i) for o in sale_orders for i in o.items), Decimal("0.00"))
    all_expenses = db.session.scalars(select(Expense)).all()
    expense_total = expense_amount_between(all_expenses, start_date, end_date)
    lifetime_expense_total = sum(
        (expense.amount for expense in all_expenses), Decimal("0.00")
    )
    lifetime_expense_remaining = sum(
        (
            expense_amount_remaining(expense, today_local)
            for expense in all_expenses
        ),
        Decimal("0.00"),
    )
    expense_deduction_count = sum(
        1
        for expense in all_expenses
        if expense_amount_between([expense], start_date, end_date) > 0
    )
    span = (end_date - start_date).days + 1
    daily_expense_schedule = []
    for day_offset in range(span):
        deduction_date = start_date + timedelta(days=day_offset)
        day_expenses = []
        for expense in all_expenses:
            amount = expense_amount_between(
                [expense], deduction_date, deduction_date
            )
            if amount > 0:
                day_expenses.append(
                    {"title": expense.title, "amount": amount}
                )
        if day_expenses:
            daily_expense_schedule.append(
                {
                    "date": deduction_date,
                    "expenses": day_expenses,
                    "total": sum(
                        (row["amount"] for row in day_expenses),
                        Decimal("0.00"),
                    ),
                }
            )
    lifetime_expense_recognized = lifetime_expense_total - lifetime_expense_remaining
    lifetime_revenue, lifetime_cogs = lifetime_sales_totals()
    lifetime_net_profit = (
        lifetime_revenue - lifetime_cogs - lifetime_expense_recognized
    )
    payments = db.session.scalars(select(Payment).join(Order).where(Payment.created_at >= start, Payment.created_at < end, Payment.status == "Recorded", Order.status == "Completed")).all()
    by_method = {key: sum((p.amount for p in payments if p.method == key), Decimal("0.00")) for key in PAYMENT_METHODS}
    item_totals = defaultdict(lambda: {"units": 0, "revenue": Decimal("0.00"), "cost": Decimal("0.00"), "orders": set()})
    for order in sale_orders:
        for item, net_line in zip(order.items, net_order_item_amounts(order)):
            row = item_totals[item.product_name]
            row["units"] += item.quantity
            row["cost"] += order_item_cost(item)
            row["orders"].add(order.id)
            row["revenue"] += net_line
    best_products = sorted(item_totals.items(), key=lambda entry: (entry[1]["revenue"] - entry[1]["cost"], entry[1]["units"]), reverse=True)
    top_revenue_products = sorted(
        item_totals.items(),
        key=lambda entry: (entry[1]["revenue"], entry[1]["units"]),
        reverse=True,
    )[:5]
    top_product_revenue = max(
        (row["revenue"] for _, row in top_revenue_products),
        default=Decimal("0.00"),
    )
    payment_total = sum(by_method.values(), Decimal("0.00"))
    payment_shares = {
        key: float(amount / payment_total * 100) if payment_total else 0
        for key, amount in by_method.items()
    }
    use_weeks = span > 31
    bucketed = defaultdict(lambda: {"sales": Decimal("0.00"), "expenses": Decimal("0.00")})
    zone = ZoneInfo("Asia/Dhaka")
    for order in sale_orders:
        local_day = order.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).date() if order.created_at.tzinfo is None else order.created_at.astimezone(zone).date()
        key = (local_day - timedelta(days=local_day.weekday())).isoformat() if use_weeks else local_day.isoformat()
        bucketed[key]["sales"] += order.total
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
    for key in chart_keys:
        bucket_start = max(date.fromisoformat(key), start_date)
        bucket_end = min(
            bucket_start + timedelta(days=6 if use_weeks else 0), end_date
        )
        bucketed[key]["expenses"] = expense_amount_between(
            all_expenses, bucket_start, bucket_end
        )
    chart_expenses = [bucketed[key]["expenses"] for key in chart_keys]
    products = db.session.scalars(select(Product).where(Product.is_archived.is_(False)).order_by(Product.name)).all()
    low_stock = [p for p in products if p.stock <= p.min_stock]
    recent_orders = db.session.scalars(
        select(Order)
        .options(joinedload(Order.created_by), joinedload(Order.accepted_by))
        .order_by(Order.created_at.desc())
        .limit(7)
    ).all()
    audit_events = db.session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(6)).all() if current_user.role in FINANCIAL_ROLES else []
    return render_template("dashboard/index.html", start_date=start_date, end_date=end_date,
                           total_revenue=total_revenue, total_cogs=total_cogs, expense_total=expense_total,
                           lifetime_expense_total=lifetime_expense_total,
                           lifetime_expense_recognized=lifetime_expense_recognized,
                           lifetime_expense_remaining=lifetime_expense_remaining,
                           expense_deduction_count=expense_deduction_count,
                           daily_expense_schedule=daily_expense_schedule,
                           lifetime_net_profit=lifetime_net_profit,
                           net_profit=total_revenue-total_cogs-expense_total, order_count=len(sale_orders),
                           average_order=total_revenue/len(sale_orders) if sale_orders else Decimal("0.00"),
                           by_method=by_method, payment_names=PAYMENT_METHODS, products=products,
                           low_stock=low_stock, out_stock=sum(1 for p in products if p.stock == 0),
                           recent_orders=recent_orders, best_products=best_products[:8], audit_events=audit_events,
                           top_revenue_products=top_revenue_products,
                           top_product_revenue=top_product_revenue,
                           chart_labels=chart_labels, chart_sales=chart_sales, chart_expenses=chart_expenses,
                           chart_sales_max=max(chart_sales, default=Decimal("0.00")),
                           chart_max=max(chart_sales + chart_expenses, default=Decimal("0.00")), chart_weekly=use_weeks,
                           payment_shares=payment_shares, today_local=today_local,
                           yesterday_local=today_local-timedelta(days=1), week_start=today_local-timedelta(days=6))


@bp.get("/overview-guide")
@login_required
def overview_guide():
    return render_template("dashboard/guide.html")


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
        audit("Updated stall settings", "Setting")
        db.session.commit()
        flash("Stall settings saved.", "success")
        return redirect(url_for("main.settings"))
    values = {key: (db.session.get(Setting, key).value if db.session.get(Setting, key) else "") for key in keys}
    if values.get("stall_name") in {"", "Festival Bites"}:
        values["stall_name"] = "HeHeFoodies"
    return render_template("settings/index.html", values=values)


@bp.app_context_processor
def inject_stall_name():
    keys = ("stall_name", "contact_info", "receipt_footer", "currency")
    values = {
        row.key: row.value
        for row in db.session.scalars(select(Setting).where(Setting.key.in_(keys)))
    }
    stall_name = values.get("stall_name", "").strip()
    if stall_name in {"", "Festival Bites"}:
        stall_name = "HeHeFoodies"
    return {
        "stall_name": stall_name,
        "stall_contact": values.get("contact_info", ""),
        "receipt_footer": values.get("receipt_footer", ""),
        "currency_symbol": values.get("currency", "").strip() or "৳",
    }
