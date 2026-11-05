from datetime import datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload
from zoneinfo import ZoneInfo

from ...extensions import db
from ...models import Ingredient, IngredientTransaction, InventoryTransaction, Product, Setting
from ...pdf_exports import build_pdf_response, pdf_money
from ...utils import FINANCIAL_ROLES, audit, cost_value, quantity_value, role_required

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def inventory_statement():
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    statement = select(Product).where(Product.is_archived.is_(False))
    if search:
        pattern = f"%{search}%"
        statement = statement.where(or_(Product.name.ilike(pattern), Product.category.ilike(pattern)))
    if status == "out":
        statement = statement.where(Product.stock == 0)
    elif status == "low":
        statement = statement.where(Product.stock > 0, Product.stock <= Product.min_stock)
    elif status == "healthy":
        statement = statement.where(Product.stock > Product.min_stock)
    return statement.order_by(Product.stock, Product.name)


@bp.get("/")
@login_required
def index():
    products = db.session.scalars(inventory_statement()).all()
    transactions = db.session.scalars(
        select(InventoryTransaction)
        .options(joinedload(InventoryTransaction.product), joinedload(InventoryTransaction.user))
        .order_by(InventoryTransaction.created_at.desc())
        .limit(80)
    ).all()
    return render_template(
        "inventory/index.html",
        products=products,
        transactions=transactions,
        q=request.args.get("q", "").strip(),
        selected_status=request.args.get("status", ""),
        low_stock_count=db.session.scalar(
            select(db.func.count(Product.id)).where(
                Product.is_archived.is_(False), Product.stock <= Product.min_stock, Product.stock > 0
            )
        ),
        out_stock_count=db.session.scalar(
            select(db.func.count(Product.id)).where(Product.is_archived.is_(False), Product.stock == 0)
        ),
        total_units=db.session.scalar(
            select(db.func.coalesce(db.func.sum(Product.stock), 0)).where(Product.is_archived.is_(False))
        ),
    )


INGREDIENT_UNITS = ("piece", "g", "kg", "ml", "L")


@bp.get("/ingredients")
@login_required
def ingredients():
    rows = db.session.scalars(
        select(Ingredient).order_by(Ingredient.active.desc(), Ingredient.name)
    ).all()
    transactions = db.session.scalars(
        select(IngredientTransaction)
        .options(joinedload(IngredientTransaction.ingredient), joinedload(IngredientTransaction.user))
        .order_by(IngredientTransaction.created_at.desc())
        .limit(80)
    ).all()
    return render_template(
        "inventory/ingredients.html",
        ingredients=rows,
        transactions=transactions,
        units=INGREDIENT_UNITS,
    )


@bp.post("/ingredients")
@login_required
@role_required("OWNER", "MANAGER")
def create_ingredient():
    try:
        name = request.form.get("name", "").strip()
        unit = request.form.get("unit", "")
        stock = quantity_value(request.form.get("stock", "0"), "opening stock")
        min_stock = quantity_value(request.form.get("min_stock", "0"), "low-stock threshold")
        unit_cost = cost_value(request.form.get("unit_cost", "0"), "unit cost")
        if not name or len(name) > 120:
            raise ValueError("Enter an ingredient name up to 120 characters.")
        if unit not in INGREDIENT_UNITS:
            raise ValueError("Choose a supported ingredient unit.")
        if db.session.scalar(select(Ingredient.id).where(Ingredient.name == name)):
            raise ValueError("An ingredient with that name already exists.")
        ingredient = Ingredient(
            name=name,
            unit=unit,
            stock=stock,
            min_stock=min_stock,
            unit_cost=unit_cost,
        )
        db.session.add(ingredient)
        db.session.flush()
        if stock:
            db.session.add(
                IngredientTransaction(
                    ingredient_id=ingredient.id,
                    previous_quantity=Decimal("0.000"),
                    quantity_changed=stock,
                    new_quantity=stock,
                    kind="Opening stock",
                    reason="Initial ingredient setup",
                    user_id=current_user.id,
                )
            )
        audit("Created ingredient", "Ingredient", ingredient.id, f"{name} ({unit})")
        db.session.commit()
        flash("Ingredient added to inventory.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("inventory.ingredients"))


@bp.post("/ingredients/<int:ingredient_id>/adjust")
@login_required
@role_required("OWNER", "MANAGER")
def adjust_ingredient(ingredient_id):
    ingredient = db.session.scalar(
        select(Ingredient).where(Ingredient.id == ingredient_id).with_for_update()
    )
    if ingredient is None:
        from flask import abort
        abort(404)
    try:
        change = quantity_value(request.form.get("quantity_changed", ""), "stock change", minimum=None)
        kind = request.form.get("kind", "Adjustment")
        reason = request.form.get("reason", "").strip()
        if change == 0 or len(reason) < 4:
            raise ValueError("Enter a nonzero stock change and a reason of at least 4 characters.")
        if kind not in {"Restock", "Adjustment", "Damaged", "Wasted"}:
            raise ValueError("Choose a valid ingredient transaction type.")
        if kind == "Restock" and change < 0:
            raise ValueError("Restock entries must add stock.")
        if kind in {"Damaged", "Wasted"} and change > 0:
            raise ValueError("Damaged and wasted entries must reduce stock.")
        previous = ingredient.stock
        new_stock = previous + change
        if new_stock < 0:
            raise ValueError("Ingredient stock cannot become negative.")
        ingredient.stock = new_stock
        db.session.add(
            IngredientTransaction(
                ingredient_id=ingredient.id,
                previous_quantity=previous,
                quantity_changed=change,
                new_quantity=new_stock,
                kind=kind,
                reason=reason[:255],
                user_id=current_user.id,
            )
        )
        audit("Adjusted ingredient inventory", "Ingredient", ingredient.id, f"{change:+}; {reason}")
        db.session.commit()
        flash("Ingredient inventory updated and recorded.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("inventory.ingredients"))


@bp.post("/ingredients/<int:ingredient_id>/details")
@login_required
@role_required("OWNER", "MANAGER")
def update_ingredient_details(ingredient_id):
    ingredient = db.get_or_404(Ingredient, ingredient_id)
    try:
        ingredient.min_stock = quantity_value(request.form.get("min_stock", ""), "low-stock threshold")
        ingredient.unit_cost = cost_value(request.form.get("unit_cost", ""), "unit cost")
        db.session.commit()
        flash("Ingredient cost and low-stock threshold updated.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("inventory.ingredients"))


@bp.get("/export.pdf")
@login_required
def export_pdf():
    products = db.session.scalars(inventory_statement()).all()
    financial_access = current_user.role in FINANCIAL_ROLES
    currency = "BDT "
    if financial_access:
        currency_setting = db.session.get(Setting, "currency")
        currency = currency_setting.value.strip() if currency_setting and currency_setting.value.strip() else "BDT "
    currency_label = "BDT" if not currency.isascii() else currency
    status_filter = request.args.get("status", "")
    filter_labels = {
        "out": "Out of stock",
        "low": "Running low",
        "healthy": "In stock",
    }
    search = request.args.get("q", "").strip()
    period = "Current stock"
    if status_filter in filter_labels:
        period += f" · {filter_labels[status_filter]}"
    if search:
        period += f" · Search: {search}"
    total_units = sum(product.stock for product in products)
    low_stock_count = sum(0 < product.stock <= product.min_stock for product in products)
    out_stock_count = sum(product.stock == 0 for product in products)
    cost_value_total = (
        sum((product.cost_price * product.stock for product in products), Decimal("0.00"))
        if financial_access
        else None
    )
    retail_value_total = (
        sum((product.selling_price * product.stock for product in products), Decimal("0.00"))
        if financial_access
        else None
    )
    rows = []
    for product in products:
        status = "Out of stock" if product.stock == 0 else "Low stock" if product.stock <= product.min_stock else "In stock"
        row = [
            (product.name, False),
            (product.category, False),
            ("Available" if product.is_available else "Hidden", False),
            (status, False),
        ]
        if financial_access:
            row.extend(
                [
                    (pdf_money(product.selling_price, currency), True),
                    (pdf_money(product.cost_price, currency), True),
                ]
            )
        row.extend([(f"{product.stock:,}", True), (f"{product.min_stock:,}", True)])
        if financial_access:
            row.extend(
                [
                    (pdf_money(product.cost_price * product.stock, currency), True),
                    (pdf_money(product.selling_price * product.stock, currency), True),
                ]
            )
        rows.append(row)
    if not rows:
        column_count = 10 if financial_access else 6
        rows.append(
            [("No products match these filters.", False)]
            + [("", False)] * (column_count - 1)
        )
    return build_pdf_response(
        title="Product inventory",
        subtitle=(
            "On-hand stock, reorder thresholds, availability, and estimated inventory value."
            if financial_access
            else "On-hand quantities, reorder thresholds, and stock status."
        ),
        period=period,
        generated_at=datetime.now(ZoneInfo("Asia/Dhaka")).strftime("%d %b %Y, %I:%M %p"),
        metrics=[
            ("Products", f"{len(products):,}"),
            ("Units on hand", f"{total_units:,}"),
            ("Running low", f"{low_stock_count:,}"),
        ]
        + (
            [
                ("Inventory cost", pdf_money(cost_value_total, currency)),
                ("Menu value", pdf_money(retail_value_total, currency)),
            ]
            if financial_access
            else []
        ),
        columns=[
            "Product",
            "Category",
            "Availability",
            "Stock status",
        ]
        + (
            ["Sale price", "Unit cost", "On hand", "Reorder at", "Stock cost", "Menu value"]
            if financial_access
            else ["On hand", "Reorder at"]
        ),
        rows=rows,
        filename="product-inventory.pdf",
        note=(
            (
                f"Values shown in {currency_label}. Stock cost and menu value are estimates "
                "based on each product's current quantity and recorded unit price."
            )
            if financial_access
            else "Inventory values reflect current on-hand quantities; hidden products are marked separately."
        ),
    )


@bp.post("/adjust")
@login_required
@role_required("OWNER", "MANAGER")
def adjust():
    product = db.session.scalar(select(Product).where(Product.id == request.form.get("product_id", type=int)).with_for_update())
    if not product:
        from flask import abort
        abort(404)
    try:
        change = int(request.form.get("quantity_changed", ""))
        reason = request.form.get("reason", "").strip()
        kind = request.form.get("kind", "Adjustment")
        if change == 0 or len(reason) < 4:
            raise ValueError("Enter a nonzero stock change and a reason of at least 4 characters.")
        if kind not in {"Restock", "Adjustment", "Damaged", "Wasted"}:
            raise ValueError("Choose a valid inventory transaction type.")
        if kind == "Restock" and change < 0:
            raise ValueError("Restock entries must add stock.")
        if kind in {"Damaged", "Wasted"} and change > 0:
            raise ValueError("Damaged and wasted entries must reduce stock.")
        new_stock = product.stock + change
        if new_stock < 0:
            raise ValueError("Stock cannot become negative.")
        previous = product.stock
        product.stock = new_stock
        db.session.add(InventoryTransaction(product_id=product.id, previous_quantity=previous,
                                            quantity_changed=change, new_quantity=new_stock, kind=kind,
                                            reason=reason[:255], user_id=current_user.id))
        audit("Adjusted inventory", "Product", product.id, f"{change:+d}; {reason}")
        db.session.commit()
        flash("Inventory updated and recorded.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("inventory.index"))
