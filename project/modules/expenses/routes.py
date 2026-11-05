from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
from ...image_uploads import save_image

from ...extensions import db
from ...models import Expense
from ...utils import (
    audit,
    decimal_value,
    expense_amount_between,
    expense_amount_remaining,
    parse_date,
    role_required,
)

bp = Blueprint("expenses", __name__, url_prefix="/expenses")
CATEGORIES = ["Ingredients", "Packaging", "Transportation", "Equipment", "Decoration", "Utilities", "Miscellaneous"]


@bp.get("/")
@login_required
@role_required("OWNER", "MANAGER")
def index():
    category = request.args.get("category", "")
    date_from = parse_date(request.args.get("date_from"), None)
    date_to = parse_date(request.args.get("date_to"), None)
    statement = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if category in CATEGORIES:
        statement = statement.where(Expense.category == category)
    if date_from:
        statement = statement.where(Expense.expense_date >= date_from)
    if date_to:
        statement = statement.where(Expense.expense_date <= date_to)
    expenses = db.session.scalars(statement.limit(300)).all()
    all_expenses = db.session.scalars(select(Expense)).all()
    today = datetime.now(ZoneInfo("Asia/Dhaka")).date()
    committed_expense_total = sum(
        (expense.amount for expense in all_expenses), Decimal("0.00")
    )
    expense_remaining_total = sum(
        (
            expense_amount_remaining(expense, today)
            for expense in all_expenses
        ),
        Decimal("0.00"),
    )
    return render_template("expenses/index.html", expenses=expenses, categories=CATEGORIES,
                           selected_category=category, date_from=date_from, date_to=date_to,
                           committed_expense_total=committed_expense_total,
                           expense_recognized_total=committed_expense_total-expense_remaining_total,
                           expense_remaining_total=expense_remaining_total,
                           expense_remaining_by_id={
                               expense.id: expense_amount_remaining(expense, today)
                               for expense in expenses
                           },
                           expense_recognized_by_id={
                               expense.id: expense.amount
                               - expense_amount_remaining(expense, today)
                               for expense in expenses
                           },
                           expense_start_by_id={
                               expense.id: expense.expense_date
                               for expense in expenses
                           })


def persist(expense=None):
    expense = expense or Expense(created_by_id=current_user.id)
    try:
        title = request.form.get("title", "").strip()
        if not title:
            raise ValueError("Enter an expense title.")
        category = request.form.get("category", "Miscellaneous")
        if category not in CATEGORIES:
            raise ValueError("Choose a valid expense category.")
        amount = decimal_value(request.form.get("amount"), "amount", minimum=decimal_value("0.01"))
        expense_date = date.fromisoformat(request.form.get("expense_date", ""))
        allocation_type = request.form.get("allocation_type", "").strip()
        if not allocation_type:
            allocation_type = (
                "once"
                if request.form.get("duration_days", "1").strip() == "1"
                else "spread"
            )
        if allocation_type not in {"once", "spread"}:
            raise ValueError("Choose whether the cost is one-time or spread over days.")
        if allocation_type == "once":
            duration_days = 1
        else:
            raw_duration = request.form.get("duration_days", "").strip()
            if not raw_duration.isdecimal():
                raise ValueError("Enter how many days to spread this expense over.")
            duration_days = int(raw_duration)
            if not 2 <= duration_days <= 36500:
                raise ValueError("Spread duration must be between 2 and 36,500 days.")
    except (ValueError, TypeError) as exc:
        flash(str(exc), "danger")
        return None
    expense.title, expense.category, expense.amount = title[:140], category, amount
    expense.expense_date = expense_date
    expense.duration_days = duration_days
    expense.description = request.form.get("description", "").strip()[:2000]
    try:
        receipt_filename = save_image(request.files.get("receipt"), "receipts")
    except ValueError as exc:
        flash(str(exc), "danger")
        return None
    if receipt_filename:
        expense.receipt_filename = receipt_filename
    db.session.add(expense)
    return expense


@bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "MANAGER")
def create():
    if request.method == "POST":
        expense = persist()
        if expense:
            db.session.flush()
            allocation = "one-time" if expense.duration_days == 1 else f"spread over {expense.duration_days} days"
            audit("Recorded expense", "Expense", expense.id, f"{expense.title}: {expense.amount}, {allocation}")
            db.session.commit()
            flash("Expense recorded.", "success")
            return redirect(url_for("expenses.index"))
    return render_template("expenses/form.html", expense=None, categories=CATEGORIES)


@bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "MANAGER")
def edit(expense_id):
    expense = db.get_or_404(Expense, expense_id)
    if request.method == "POST":
        old_allocation = "one-time" if expense.duration_days == 1 else f"spread over {expense.duration_days} days"
        old = f"{expense.title} {expense.amount}, {old_allocation}"
        saved = persist(expense)
        if saved:
            new_allocation = "one-time" if expense.duration_days == 1 else f"spread over {expense.duration_days} days"
            audit("Edited expense", "Expense", expense.id, f"Before: {old}; after: {expense.title} {expense.amount}, {new_allocation}")
            db.session.commit()
            flash("Expense updated and the change was recorded.", "success")
            return redirect(url_for("expenses.index"))
    return render_template("expenses/form.html", expense=expense, categories=CATEGORIES)


@bp.post("/<int:expense_id>/delete")
@login_required
@role_required("OWNER", "MANAGER")
def delete(expense_id):
    expense = db.get_or_404(Expense, expense_id)
    receipt_filename = expense.receipt_filename
    details = f"{expense.title}; {expense.category}; {expense.amount}; {expense.expense_date}; {expense.duration_days} days"
    audit("Deleted expense", "Expense", expense.id, details)
    db.session.delete(expense)
    db.session.commit()

    receipt_deleted = True
    if receipt_filename:
        parts = Path(receipt_filename).parts
        if len(parts) != 2 or parts[0] != "receipts":
            current_app.logger.error(
                "Not deleting expense receipt with unexpected path: %r",
                receipt_filename,
            )
            receipt_deleted = False
        else:
            receipt_directory = (
                Path(current_app.instance_path) / "uploads" / "receipts"
            ).resolve()
            receipt_path = (receipt_directory / parts[1]).resolve()
            if receipt_path.parent != receipt_directory:
                current_app.logger.error(
                    "Not deleting expense receipt outside receipt directory: %r",
                    receipt_filename,
                )
                receipt_deleted = False
            else:
                try:
                    receipt_path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.exception(
                        "Could not remove receipt for deleted expense %s.",
                        expense_id,
                    )
                    receipt_deleted = False

    flash(
        "Expense deleted." if receipt_deleted else "Expense deleted, but its receipt file could not be removed.",
        "success" if receipt_deleted else "warning",
    )
    return redirect(url_for("expenses.index"))
