import csv
from collections import defaultdict
from decimal import Decimal
from io import StringIO

from flask import Blueprint, Response, render_template
from flask_login import login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from ...extensions import db
from ...models import Expense, Order, OrderItem, Payment
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, net_order_item_amounts, order_item_cost, role_required, selected_window

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("/")
@login_required
@role_required(*FINANCIAL_ROLES)
def index():
    start_date, end_date, start, end = selected_window(7)
    orders = db.session.scalars(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.addons),
            joinedload(Order.created_by),
        )
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.created_at)
    ).all()
    completed = [o for o in orders if o.status == "Completed"]
    expenses = db.session.scalars(select(Expense).where(Expense.expense_date >= start_date, Expense.expense_date <= end_date).order_by(Expense.expense_date)).all()
    expense_by_category = defaultdict(lambda: Decimal("0.00"))
    for expense in expenses:
        expense_by_category[expense.category] += expense.amount
    revenue = sum((o.total for o in completed), Decimal("0.00"))
    cogs = sum((order_item_cost(i) for o in completed for i in o.items), Decimal("0.00"))
    expense_total = sum((e.amount for e in expenses), Decimal("0.00"))
    product_rows = defaultdict(lambda: {"units": 0, "revenue": Decimal("0.00"), "cost": Decimal("0.00"), "orders": set()})
    for order in completed:
        for item, net_line in zip(order.items, net_order_item_amounts(order)):
            row = product_rows[item.product_name]
            row["units"] += item.quantity
            row["cost"] += order_item_cost(item)
            row["orders"].add(order.id)
            row["revenue"] += net_line
    products = sorted(product_rows.items(), key=lambda x: (x[1]["revenue"]-x[1]["cost"], x[1]["units"]), reverse=True)
    payments = db.session.scalars(
        select(Payment)
        .options(joinedload(Payment.order))
        .join(Order)
        .where(Payment.created_at >= start, Payment.created_at < end)
    ).all()
    payment_summary = {key: sum((p.amount for p in payments if p.method == key and p.status == "Recorded" and p.order.status == "Completed"), Decimal("0.00")) for key in PAYMENT_METHODS}
    payment_count = {key: sum(1 for p in payments if p.method == key and p.status == "Recorded" and p.order.status == "Completed") for key in PAYMENT_METHODS}
    cashier_rows = defaultdict(lambda: {"count": 0, "sales": Decimal("0.00")})
    for order in completed:
        row = cashier_rows[order.created_by.full_name]
        row["count"] += 1
        row["sales"] += order.total
    cashier_rows = sorted(cashier_rows.items(), key=lambda x: x[1]["sales"], reverse=True)
    return render_template("reports/index.html", start_date=start_date, end_date=end_date, orders=completed,
                           expenses=expenses, revenue=revenue, cogs=cogs, expense_total=expense_total,
                           net_profit=revenue-cogs-expense_total, products=products,
                           payment_summary=payment_summary, payment_names=PAYMENT_METHODS,
                           cashier_rows=cashier_rows, payment_count=payment_count,
                           expense_by_category=sorted(expense_by_category.items()))


@bp.get("/products.csv")
@login_required
@role_required(*FINANCIAL_ROLES)
def products_csv():
    start_date, end_date, start, end = selected_window(7)
    orders = db.session.scalars(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.addons))
        .where(Order.status == "Completed", Order.created_at >= start, Order.created_at < end)
    ).all()
    rows = defaultdict(lambda: {"units": 0, "revenue": Decimal("0.00"), "cost": Decimal("0.00"), "orders": set()})
    for order in orders:
        for item, net in zip(order.items, net_order_item_amounts(order)):
            row = rows[item.product_name]
            row["units"] += item.quantity
            row["cost"] += order_item_cost(item)
            row["orders"].add(order.id)
            row["revenue"] += net
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Product", "Units sold", "Sales revenue", "Cost of goods", "Gross profit", "Orders"])
    for name, row in sorted(rows.items(), key=lambda x: x[1]["revenue"]-x[1]["cost"], reverse=True):
        safe_name = f"'{name}" if name.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else name
        writer.writerow([safe_name, row["units"], row["revenue"], row["cost"], row["revenue"]-row["cost"], len(row["orders"])])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=product-performance-{start_date}-{end_date}.csv"})
