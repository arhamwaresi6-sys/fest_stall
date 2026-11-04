from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
from ...image_uploads import save_image

from ...extensions import db
from ...models import Expense
from ...utils import audit, decimal_value, parse_date, role_required

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
    return render_template("expenses/index.html", expenses=expenses, categories=CATEGORIES,
                           selected_category=category, date_from=date_from, date_to=date_to)


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
    except (ValueError, TypeError) as exc:
        flash(str(exc), "danger")
        return None
    expense.title, expense.category, expense.amount = title[:140], category, amount
    expense.expense_date = expense_date
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
            audit("Recorded expense", "Expense", expense.id, f"{expense.title}: {expense.amount}")
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
        old = f"{expense.title} {expense.amount}"
        saved = persist(expense)
        if saved:
            audit("Edited expense", "Expense", expense.id, f"Before: {old}; after: {expense.title} {expense.amount}")
            db.session.commit()
            flash("Expense updated and the change was recorded.", "success")
            return redirect(url_for("expenses.index"))
    return render_template("expenses/form.html", expense=expense, categories=CATEGORIES)
