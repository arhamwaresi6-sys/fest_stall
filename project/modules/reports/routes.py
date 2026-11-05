from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from ...extensions import db
from ...models import Expense, Order, OrderItem, Payment, Setting
from ...pdf_exports import build_pdf_response, pdf_money
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, expense_amount_between, expense_amount_remaining, lifetime_sales_totals, net_order_item_amounts, order_item_cost, role_required, selected_window

bp = Blueprint("reports", __name__, url_prefix="/reports")


def product_performance(orders):
    rows = defaultdict(
        lambda: {
            "units": 0,
            "revenue": Decimal("0.00"),
            "cost": Decimal("0.00"),
            "orders": set(),
        }
    )
    for order in orders:
        for item, net in zip(order.items, net_order_item_amounts(order)):
            row = rows[item.product_name]
            row["units"] += item.quantity
            row["cost"] += order_item_cost(item)
            row["orders"].add(order.id)
            row["revenue"] += net
    return sorted(
        rows.items(),
        key=lambda item: (
            item[1]["revenue"] - item[1]["cost"],
            item[1]["units"],
        ),
        reverse=True,
    )


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
    all_expenses = db.session.scalars(
        select(Expense).order_by(Expense.expense_date)
    ).all()
    period_expense_count = sum(
        1
        for expense in all_expenses
        if expense_amount_between([expense], start_date, end_date) > 0
    )
    lifetime_expense_rows = db.session.execute(
        select(Expense.category, func.sum(Expense.amount))
        .group_by(Expense.category)
        .order_by(Expense.category)
    ).all()
    lifetime_expense_total = sum(
        (expense.amount for expense in all_expenses), Decimal("0.00")
    )
    lifetime_expense_remaining = sum(
        (
            expense_amount_remaining(expense, end_date)
            for expense in all_expenses
        ),
        Decimal("0.00"),
    )
    lifetime_revenue, lifetime_cogs = lifetime_sales_totals()
    lifetime_net_profit = (
        lifetime_revenue
        - lifetime_cogs
        - (lifetime_expense_total - lifetime_expense_remaining)
    )
    revenue = sum((o.total for o in completed), Decimal("0.00"))
    cogs = sum((order_item_cost(i) for o in completed for i in o.items), Decimal("0.00"))
    expense_total = expense_amount_between(all_expenses, start_date, end_date)
    products = product_performance(completed)
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
                           expenses=all_expenses, revenue=revenue, cogs=cogs, expense_total=expense_total,
                           net_profit=revenue-cogs-expense_total, products=products,
                           payment_summary=payment_summary, payment_names=PAYMENT_METHODS,
                           cashier_rows=cashier_rows, payment_count=payment_count,
                           lifetime_expense_by_category=[
                               (category, amount)
                               for category, amount in lifetime_expense_rows
                           ],
                           lifetime_expense_total=lifetime_expense_total,
                           lifetime_expense_remaining=lifetime_expense_remaining,
                           lifetime_net_profit=lifetime_net_profit,
                           period_expense_count=period_expense_count)


@bp.get("/products.pdf")
@login_required
@role_required(*FINANCIAL_ROLES)
def products_pdf():
    start_date, end_date, start, end = selected_window(7)
    orders = db.session.scalars(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.addons))
        .where(Order.status == "Completed", Order.created_at >= start, Order.created_at < end)
    ).all()
    products = product_performance(orders)
    currency_setting = db.session.get(Setting, "currency")
    currency = currency_setting.value.strip() if currency_setting and currency_setting.value.strip() else "BDT "
    currency_label = "BDT" if not currency.isascii() else currency
    revenue = sum((row["revenue"] for _, row in products), Decimal("0.00"))
    cost = sum((row["cost"] for _, row in products), Decimal("0.00"))
    gross_profit = revenue - cost
    order_count = len({order.id for order in orders})
    rows = []
    for rank, (name, row) in enumerate(products, start=1):
        profit = row["revenue"] - row["cost"]
        margin = profit * 100 / row["revenue"] if row["revenue"] else Decimal("0")
        average_units = Decimal(row["units"]) / len(row["orders"]) if row["orders"] else Decimal("0")
        rows.append(
            [
                (str(rank), True),
                (name, False),
                (f"{row['units']:,}", True),
                (f"{len(row['orders']):,}", True),
                (f"{average_units:.1f}", True),
                (pdf_money(row["revenue"], currency), True),
                (pdf_money(row["cost"], currency), True),
                (pdf_money(profit, currency), True),
                (f"{margin:.1f}%", True),
            ]
        )
    if not rows:
        rows.append([("—", False), ("No completed product sales in this period.", False)] + [("", False)] * 7)
    margin_total = gross_profit * 100 / revenue if revenue else Decimal("0")
    return build_pdf_response(
        title="Product performance",
        subtitle="Sales volume, discount-adjusted revenue, costs, and gross profit by product.",
        period=f"{start_date:%d %b %Y} – {end_date:%d %b %Y}",
        generated_at=datetime.now(ZoneInfo("Asia/Dhaka")).strftime("%d %b %Y, %I:%M %p"),
        metrics=[
            ("Completed orders", f"{order_count:,}"),
            ("Products sold", f"{len(products):,}"),
            ("Net revenue", pdf_money(revenue, currency)),
            ("Cost of goods", pdf_money(cost, currency)),
            ("Gross profit", pdf_money(gross_profit, currency)),
        ],
        columns=[
            "Rank",
            "Product",
            "Units sold",
            "Orders",
            "Units / order",
            "Net revenue",
            "Cost of goods",
            "Gross profit",
            "Margin",
        ],
        rows=rows,
        filename=f"product-performance-{start_date}-{end_date}.pdf",
        note=(
            f"Values shown in {currency_label}. Net revenue includes allocated order discounts; "
            f"overall gross margin for this period is {margin_total:.1f}%."
        ),
    )
