import csv
from decimal import Decimal
from io import StringIO

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from ...extensions import db
from ...models import Ingredient, IngredientTransaction, InventoryTransaction, Product
from ...utils import audit, cost_value, quantity_value, role_required

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


@bp.get("/export.csv")
@login_required
def export_csv():
    products = db.session.scalars(inventory_statement()).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Product", "Category", "Quantity on hand", "Low-stock threshold", "Status"])
    for product in products:
        name = f"'{product.name}" if product.name.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else product.name
        category = f"'{product.category}" if product.category.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else product.category
        status = "Out of stock" if product.stock == 0 else "Low stock" if product.stock <= product.min_stock else "In stock"
        writer.writerow([name, category, product.stock, product.min_stock, status])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
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
