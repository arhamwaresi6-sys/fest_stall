from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from ...image_uploads import save_image

from ...extensions import db
from ...models import InventoryTransaction, Order, OrderItem, Product, Setting
from ...utils import PRODUCT_ROLES, audit, decimal_value, role_required

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
    return render_template("products/form.html", product=None, title="Add product",
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
    return render_template("products/form.html", product=product, title="Edit product", default_min_stock=product.min_stock)


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
