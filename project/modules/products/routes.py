from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from decimal import Decimal
from ...image_uploads import save_image

from ...extensions import db
from ...models import Ingredient, InventoryTransaction, Order, OrderItem, Product, ProductAddon, Setting
from ...utils import PRODUCT_ROLES, audit, decimal_value, quantity_value, role_required

bp = Blueprint("products", __name__, url_prefix="/products")


@bp.get("/")
@login_required
def index():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    statement = select(Product).where(Product.is_archived.is_(False))
    if query:
        statement = statement.where(or_(Product.name.ilike(f"%{query}%"), Product.category.ilike(f"%{query}%")))
    if category:
        statement = statement.where(Product.category == category)
    sort = request.args.get("sort")
    if sort == "price":
        statement = statement.order_by(Product.selling_price.desc())
    else:
        statement = statement.order_by(Product.name)
    products = db.session.scalars(statement).all()
    if sort == "popularity":
        counts = dict(db.session.execute(select(OrderItem.product_id, db.func.coalesce(db.func.sum(OrderItem.quantity), 0))
                                         .join(Order, Order.id == OrderItem.order_id)
                                         .where(Order.status == "Completed", OrderItem.product_id.is_not(None))
                                         .group_by(OrderItem.product_id)).all())
        products.sort(key=lambda product: (-counts.get(product.id, 0), product.name.lower()))
    categories = db.session.scalars(select(Product.category).where(Product.is_archived.is_(False)).distinct().order_by(Product.category)).all()
    return render_template("products/index.html", products=products, categories=categories, q=query, selected_category=category)


def save_product(product=None):
    product = product or Product()
    try:
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Other").strip() or "Other"
        if not name or len(name) > 120:
            raise ValueError("Enter a product name up to 120 characters.")
        price = decimal_value(request.form.get("selling_price"), "selling price")
        cost = decimal_value(request.form.get("cost_price", "0"), "cost price")
        stock = int(request.form.get("stock", "0"))
        min_stock = int(request.form.get("min_stock", "5"))
        if stock < 0 or min_stock < 0:
            raise ValueError("Stock values cannot be negative.")
        addon_rows = []
        seen_ingredients = set()
        ingredient_ids = request.form.getlist("addon_ingredient_id")
        quantities = request.form.getlist("addon_quantity")
        prices = request.form.getlist("addon_price")
        if len(ingredient_ids) > 50:
            raise ValueError("A product can have up to 50 add-ons.")
        for index, ingredient_id in enumerate(ingredient_ids):
            quantity = quantities[index] if index < len(quantities) else ""
            addon_price_input = prices[index] if index < len(prices) else ""
            if not ingredient_id and not quantity and not addon_price_input:
                continue
            try:
                ingredient_id = int(ingredient_id)
            except (TypeError, ValueError):
                raise ValueError("Choose an ingredient for every add-on.")
            if ingredient_id in seen_ingredients:
                raise ValueError("Each ingredient can only be added once per product.")
            seen_ingredients.add(ingredient_id)
            amount = quantity_value(quantity, "ingredient quantity", minimum=Decimal("0.001"))
            addon_price = decimal_value(addon_price_input, "add-on price")
            addon_rows.append((ingredient_id, amount, addon_price))
        if addon_rows:
            ingredients = db.session.scalars(
                select(Ingredient).where(
                    Ingredient.id.in_([row[0] for row in addon_rows]),
                    Ingredient.active.is_(True),
                )
            ).all()
            if len(ingredients) != len(addon_rows):
                raise ValueError("One of the selected ingredients is no longer available.")
            ingredient_by_id = {ingredient.id: ingredient for ingredient in ingredients}
            addon_rows = [(ingredient_by_id[ingredient_id], amount, price)
                          for ingredient_id, amount, price in addon_rows]
    except (ValueError, TypeError) as exc:
        flash(str(exc), "danger")
        return None
    product.name, product.category = name, category[:80]
    product.description = request.form.get("description", "").strip()[:2000]
    try:
        image_filename = save_image(request.files.get("image"), "products")
    except ValueError as exc:
        flash(str(exc), "danger")
        return None
    if image_filename:
        product.image_filename = image_filename
    product.selling_price, product.cost_price = price, cost
    product.min_stock = min_stock
    if product.id is None:
        product.stock = stock
    product.is_available = request.form.get("is_available") == "on"
    existing_addons = {addon.ingredient_id: addon for addon in product.addons}
    desired_ingredient_ids = {ingredient.id for ingredient, _, _ in addon_rows}
    for ingredient_id, addon in existing_addons.items():
        if ingredient_id not in desired_ingredient_ids:
            product.addons.remove(addon)
    for ingredient, amount, addon_price in addon_rows:
        addon = existing_addons.get(ingredient.id)
        if addon:
            addon.quantity_used = amount
            addon.unit_price = addon_price
        else:
            product.addons.append(
                ProductAddon(ingredient=ingredient, quantity_used=amount, unit_price=addon_price)
            )
    db.session.add(product)
    return product


@bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required(*PRODUCT_ROLES)
def create():
    if request.method == "POST":
        product = save_product()
        if product:
            db.session.flush()
            if product.stock:
                db.session.add(InventoryTransaction(product_id=product.id, previous_quantity=0,
                                                    quantity_changed=product.stock, new_quantity=product.stock,
                                                    kind="Opening stock", reason="Initial product setup",
                                                    user_id=current_user.id))
            audit("Created product", "Product", product.id, product.name)
            db.session.commit()
            flash("Product added.", "success")
            return redirect(url_for("products.index"))
    threshold = db.session.get(Setting, "low_stock_threshold")
    addon_ingredients = db.session.scalars(
        select(Ingredient).where(Ingredient.active.is_(True)).order_by(Ingredient.name)
    ).all()
    return render_template("products/form.html", product=None, title="Add product",
                           addon_ingredients=addon_ingredients,
                           default_min_stock=int(threshold.value) if threshold and threshold.value.isdigit() else 5)


@bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(*PRODUCT_ROLES)
def edit(product_id):
    product = db.get_or_404(Product, product_id)
    if request.method == "POST":
        old_price = product.selling_price
        saved = save_product(product)
        if saved:
            audit("Updated product", "Product", product.id, f"{product.name}; price {old_price} → {product.selling_price}")
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("products.index"))
    addon_ingredients = db.session.scalars(
        select(Ingredient).where(Ingredient.active.is_(True)).order_by(Ingredient.name)
    ).all()
    return render_template("products/form.html", product=product, title="Edit product",
                           addon_ingredients=addon_ingredients, default_min_stock=product.min_stock)


@bp.post("/<int:product_id>/archive")
@login_required
@role_required(*PRODUCT_ROLES)
def archive(product_id):
    product = db.get_or_404(Product, product_id)
    product.is_archived = True
    audit("Archived product", "Product", product.id, product.name)
    db.session.commit()
    flash("Product archived. Past sales remain available in reports.", "success")
    return redirect(url_for("products.index"))
