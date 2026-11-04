import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ...extensions import db
from ...models import (
    Ingredient,
    IngredientTransaction,
    InventoryTransaction,
    Order,
    OrderItem,
    OrderItemAddon,
    Payment,
    Product,
    ProductAddon,
    User,
)
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, audit, date_window, decimal_value, parse_date, refresh_order_payment_status, role_required

bp = Blueprint("sales", __name__)
ORDER_ACCEPTOR_ROLES = ("ROOT", "OWNER", "MANAGER", "CASHIER")


def restore_order_stock(order, kind, reason):
    quantities = {}
    ingredient_quantities = {}
    for item in order.items:
        if item.product_id is not None:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        for addon in item.addons:
            if addon.ingredient_id is not None:
                used = addon.quantity_per_product * item.quantity
                ingredient_quantities[addon.ingredient_id] = (
                    ingredient_quantities.get(addon.ingredient_id, Decimal("0.000")) + used
                )
    products = db.session.scalars(select(Product).where(Product.id.in_(sorted(quantities))).order_by(Product.id).with_for_update()).all() if quantities else []
    by_id = {product.id: product for product in products}
    for product_id, quantity in quantities.items():
        product = by_id.get(product_id)
        if product is None:
            continue
        previous = product.stock
        product.stock += quantity
        db.session.add(InventoryTransaction(product_id=product.id, previous_quantity=previous,
                                            quantity_changed=quantity, new_quantity=product.stock,
                                            kind=kind, reason=f"Order {order.order_number}: {reason}",
                                            user_id=current_user.id, order_id=order.id))
    ingredients = db.session.scalars(
        select(Ingredient)
        .where(Ingredient.id.in_(sorted(ingredient_quantities)))
        .order_by(Ingredient.id)
        .with_for_update()
    ).all() if ingredient_quantities else []
    for ingredient in ingredients:
        quantity = ingredient_quantities[ingredient.id]
        previous = ingredient.stock
        ingredient.stock += quantity
        db.session.add(
            IngredientTransaction(
                ingredient_id=ingredient.id,
                previous_quantity=previous,
                quantity_changed=quantity,
                new_quantity=ingredient.stock,
                kind=kind,
                reason=f"Order {order.order_number}: {reason}",
                user_id=current_user.id,
                order_id=order.id,
            )
        )


@bp.route("/pos", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def pos():
    selected_acceptor_id = request.form.get("accepted_by_id", str(current_user.id))
    if request.method == "POST":
        try:
            checkout_token = request.form.get("checkout_token", "").strip()
            if not checkout_token:
                raise ValueError("This checkout form expired. Please review your cart and try again.")
            existing = db.session.scalar(select(Order).where(Order.checkout_token == checkout_token))
            if existing:
                flash("This order was already saved.", "success")
                return redirect(url_for("sales.order_detail", order_id=existing.id))
            try:
                accepted_by_id = int(selected_acceptor_id)
            except (TypeError, ValueError):
                raise ValueError("Choose an active user who can accept orders.")
            accepted_by = db.session.scalar(
                select(User).where(
                    User.id == accepted_by_id,
                    User.active.is_(True),
                    User.role.in_(ORDER_ACCEPTOR_ROLES),
                )
            )
            if accepted_by is None:
                raise ValueError("Choose an active user who can accept orders.")
            cart = json.loads(request.form.get("cart", "[]"))
            payment_rows = json.loads(request.form.get("payments", "[]"))
            if not isinstance(cart, list) or not cart or len(cart) > 100:
                raise ValueError("Add at least one product to the cart.")
            if not isinstance(payment_rows, list) or len(payment_rows) > 100:
                raise ValueError("Payment details are invalid.")
            lines = []
            quantities = {}
            for row in cart:
                if not isinstance(row, dict):
                    raise ValueError("Cart details are invalid.")
                product_id = int(row.get("id"))
                quantity = int(row.get("quantity"))
                if quantity < 1 or quantity > 999:
                    raise ValueError("Each quantity must be between 1 and 999.")
                quantities[product_id] = quantities.get(product_id, 0) + quantity
                if quantities[product_id] > 999:
                    raise ValueError("A product quantity cannot exceed 999.")
                addon_ids = row.get("addons", [])
                if not isinstance(addon_ids, list) or len(addon_ids) > 50:
                    raise ValueError("Product add-on details are invalid.")
                try:
                    addon_ids = [int(addon_id) for addon_id in addon_ids]
                except (TypeError, ValueError):
                    raise ValueError("Product add-on details are invalid.")
                if len(set(addon_ids)) != len(addon_ids):
                    raise ValueError("An add-on can only be selected once per product.")
                lines.append({"product_id": product_id, "quantity": quantity, "addon_ids": addon_ids})
            product_rows = db.session.scalars(
                select(Product)
                .options(selectinload(Product.addons).joinedload(ProductAddon.ingredient))
                .where(Product.id.in_(sorted(quantities)))
                .order_by(Product.id)
                .with_for_update()
            ).all()
            by_id = {product.id: product for product in product_rows}
            if set(by_id) != set(quantities):
                raise ValueError("One of the selected products is no longer available.")
            for product_id, quantity in quantities.items():
                product = by_id[product_id]
                if product.is_archived or not product.is_available:
                    raise ValueError(f"{product.name} is not available for sale.")
                if product.stock < quantity:
                    raise ValueError(f"Not enough stock for {product.name}; only {product.stock} left.")

            required_ingredients = {}
            line_addons = []
            for line in lines:
                product = by_id[line["product_id"]]
                addon_by_ingredient = {addon.ingredient_id: addon for addon in product.addons}
                if any(addon_id not in addon_by_ingredient for addon_id in line["addon_ids"]):
                    raise ValueError(f"One of the selected extras is not available for {product.name}.")
                chosen = [addon_by_ingredient[addon_id] for addon_id in line["addon_ids"]]
                for addon in chosen:
                    ingredient_id = addon.ingredient_id
                    amount = addon.quantity_used * line["quantity"]
                    required_ingredients[ingredient_id] = (
                        required_ingredients.get(ingredient_id, Decimal("0.000")) + amount
                    )
                line_addons.append(chosen)
            ingredient_rows = db.session.scalars(
                select(Ingredient)
                .where(
                    Ingredient.id.in_(sorted(required_ingredients)),
                    Ingredient.active.is_(True),
                )
                .order_by(Ingredient.id)
                .with_for_update()
            ).all() if required_ingredients else []
            ingredient_by_id = {ingredient.id: ingredient for ingredient in ingredient_rows}
            if set(ingredient_by_id) != set(required_ingredients):
                raise ValueError("One of the selected ingredients is no longer available.")
            for ingredient_id, amount in required_ingredients.items():
                ingredient = ingredient_by_id[ingredient_id]
                if ingredient.stock < amount:
                    raise ValueError(
                        f"Not enough {ingredient.name}; only {ingredient.stock} {ingredient.unit} left."
                    )

            subtotal = sum(
                (
                    (by_id[line["product_id"]].selling_price
                     + sum((addon.unit_price for addon in addons), Decimal("0.00")))
                    * line["quantity"]
                    for line, addons in zip(lines, line_addons)
                ),
                Decimal("0.00"),
            )
            discount_input = decimal_value(request.form.get("discount", "0"), "discount")
            discount_kind = request.form.get("discount_kind", "amount")
            if discount_input > 0 and current_user.role not in FINANCIAL_ROLES:
                raise ValueError("Only an owner or manager can apply a discount.")
            if discount_kind == "percent":
                if discount_input > 100:
                    raise ValueError("Percentage discount cannot exceed 100%.")
                discount = (subtotal * discount_input / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            elif discount_kind == "amount":
                discount = discount_input
            else:
                raise ValueError("Choose a valid discount type.")
            if discount > subtotal:
                raise ValueError("Discount cannot exceed the subtotal.")
            total = subtotal - discount
            valid_payments = []
            for payment in payment_rows:
                if not isinstance(payment, dict):
                    raise ValueError("Payment details are invalid.")
                method = payment.get("method")
                if method not in PAYMENT_METHODS:
                    raise ValueError("Choose By hand (cash) or bKash for each payment.")
                amount = decimal_value(payment.get("amount"), "payment", minimum=Decimal("0.01"))
                valid_payments.append((method, amount, str(payment.get("reference", ""))[:120]))
            if sum((p[1] for p in valid_payments), Decimal("0.00")) > total:
                raise ValueError("Payments cannot exceed the amount due.")

            order = Order(order_number=f"FS-{datetime.now(timezone.utc):%y%m%d}-{uuid4().hex[:6].upper()}",
                          checkout_token=checkout_token,
                          subtotal=subtotal, discount=discount, total=total,
                          notes=request.form.get("notes", "").strip()[:2000] or None,
                          created_by_id=current_user.id,
                          accepted_by_id=accepted_by.id)
            db.session.add(order)
            db.session.flush()
            for line, addons in zip(lines, line_addons):
                product = by_id[line["product_id"]]
                quantity = line["quantity"]
                unit_price = product.selling_price + sum(
                    (addon.unit_price for addon in addons), Decimal("0.00")
                )
                order_item = OrderItem(
                    product_id=product.id,
                    product_name=product.name,
                    unit_price=product.selling_price,
                    unit_cost=product.cost_price,
                    quantity=quantity,
                    line_total=unit_price * quantity,
                )
                for addon in addons:
                    ingredient = ingredient_by_id[addon.ingredient_id]
                    order_item.addons.append(
                        OrderItemAddon(
                            ingredient_id=ingredient.id,
                            ingredient_name=ingredient.name,
                            ingredient_unit=ingredient.unit,
                            quantity_per_product=addon.quantity_used,
                            unit_price=addon.unit_price,
                            unit_cost=ingredient.unit_cost,
                        )
                    )
                order.items.append(order_item)
                previous = product.stock
                product.stock -= quantity
                db.session.add(InventoryTransaction(product_id=product.id, previous_quantity=previous,
                                                    quantity_changed=-quantity, new_quantity=product.stock,
                                                    kind="Sale", reason=f"Order {order.order_number}",
                                                    user_id=current_user.id, order_id=order.id))
            for ingredient_id, amount in required_ingredients.items():
                ingredient = ingredient_by_id[ingredient_id]
                previous = ingredient.stock
                ingredient.stock -= amount
                db.session.add(
                    IngredientTransaction(
                        ingredient_id=ingredient.id,
                        previous_quantity=previous,
                        quantity_changed=-amount,
                        new_quantity=ingredient.stock,
                        kind="Sale",
                        reason=f"Order {order.order_number}",
                        user_id=current_user.id,
                        order_id=order.id,
                    )
                )
            for method, amount, reference in valid_payments:
                order.payments.append(Payment(amount=amount, method=method, status="Recorded", reference_id=reference or None,
                                              recorded_by_id=current_user.id))
            refresh_order_payment_status(order)
            audit("Created order", "Order", order.id, order.order_number)
            db.session.commit()
            flash(f"Order {order.order_number} saved.", "success")
            return redirect(url_for("sales.order_detail", order_id=order.id))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except IntegrityError:
            db.session.rollback()
            existing = db.session.scalar(select(Order).where(Order.checkout_token == request.form.get("checkout_token", "")))
            if existing:
                flash("This order was already saved.", "success")
                return redirect(url_for("sales.order_detail", order_id=existing.id))
            flash("The order could not be saved. Please check available stock and try again.", "danger")
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Database error while saving an order.")
            flash("The order could not be saved because of a database error. Please contact the owner.", "danger")
    products = db.session.scalars(
        select(Product)
        .options(selectinload(Product.addons).joinedload(ProductAddon.ingredient))
        .where(
            Product.is_archived.is_(False),
            Product.is_available.is_(True),
            Product.stock > 0,
        )
        .order_by(Product.category, Product.name)
    ).all()
    categories = sorted({p.category for p in products})
    product_addons = {
        product.id: [
            {
                "id": addon.ingredient_id,
                "name": addon.ingredient.name,
                "unit": addon.ingredient.unit,
                "stock": str(addon.ingredient.stock),
                "amount": str(addon.quantity_used),
                "price": str(addon.unit_price),
            }
            for addon in product.addons
            if addon.ingredient.active
        ]
        for product in products
    }
    order_acceptors = db.session.scalars(
        select(User)
        .where(User.active.is_(True), User.role.in_(ORDER_ACCEPTOR_ROLES))
        .order_by(User.full_name, User.username)
    ).all()
    return render_template("sales/pos.html", products=products, categories=categories, payment_methods=PAYMENT_METHODS,
                           checkout_token=secrets.token_urlsafe(32), order_acceptors=order_acceptors,
                           selected_acceptor_id=selected_acceptor_id, product_addons=product_addons)


@bp.get("/orders")
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def orders():
    statement = (
        select(Order)
        .options(
            selectinload(Order.payments),
            joinedload(Order.created_by),
            joinedload(Order.accepted_by),
        )
        .order_by(Order.created_at.desc())
    )
    query = request.args.get("q", "").strip()
    method = request.args.get("method", "")
    status = request.args.get("status", "")
    payment_status = request.args.get("payment_status", "")
    date_from = parse_date(request.args.get("date_from"), None)
    date_to = parse_date(request.args.get("date_to"), None)
    if date_from:
        window_start, _ = date_window(date_from, date_from)
        statement = statement.where(Order.created_at >= window_start)
    if date_to:
        _, window_end = date_window(date_to, date_to)
        statement = statement.where(Order.created_at < window_end)
    if query:
        statement = statement.where(or_(Order.order_number.ilike(f"%{query}%"), Order.customer_name.ilike(f"%{query}%"), Order.reference.ilike(f"%{query}%")))
    if status in {"Completed", "Cancelled", "Refunded"}:
        statement = statement.where(Order.status == status)
    if payment_status in {"Paid", "Partially paid", "Unpaid", "Refunded"}:
        statement = statement.where(Order.payment_status == payment_status)
    found = db.session.scalars(statement.limit(300)).all()
    if method in PAYMENT_METHODS:
        found = [o for o in found if any(p.method == method and p.status == "Recorded" for p in o.payments)]
    return render_template("orders/index.html", orders=found, q=query, selected_method=method, selected_status=status,
                           selected_payment_status=payment_status, date_from=date_from, date_to=date_to,
                           payment_methods=PAYMENT_METHODS)


@bp.get("/orders/<int:order_id>")
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def order_detail(order_id):
    order = db.session.scalar(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.addons),
            selectinload(Order.payments),
            joinedload(Order.created_by),
            joinedload(Order.accepted_by),
        )
        .where(Order.id == order_id)
    )
    if order is None:
        from flask import abort
        abort(404)
    received = sum((p.amount for p in order.payments if p.status == "Recorded"), Decimal("0.00"))
    remaining = max(Decimal("0.00"), order.total - received)
    return render_template("orders/detail.html", order=order, received=received, remaining=remaining,
                           payment_methods=PAYMENT_METHODS, payment_names=PAYMENT_METHODS)


@bp.post("/orders/<int:order_id>/payments")
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def add_payment(order_id):
    order = db.session.scalar(
        select(Order)
        .options(selectinload(Order.payments))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        from flask import abort
        abort(404)
    try:
        if order.status != "Completed":
            raise ValueError("Payments can only be added to completed orders.")
        method = request.form.get("method")
        if method not in PAYMENT_METHODS:
            raise ValueError("Choose By hand (cash) or bKash.")
        amount = decimal_value(request.form.get("amount"), "payment", minimum=Decimal("0.01"))
        received = sum((p.amount for p in order.payments if p.status == "Recorded"), Decimal("0.00"))
        if amount > order.total - received:
            raise ValueError("Payment cannot exceed the amount remaining.")
        order.payments.append(Payment(amount=amount, method=method, status="Recorded",
                                      reference_id=request.form.get("reference_id", "").strip()[:120] or None,
                                      notes=request.form.get("notes", "").strip()[:1000] or None,
                                      recorded_by_id=current_user.id))
        db.session.flush()
        refresh_order_payment_status(order)
        audit("Recorded payment", "Order", order.id, f"{amount} by {PAYMENT_METHODS[method]}")
        db.session.commit()
        flash("Payment recorded.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("sales.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/void")
@login_required
@role_required("OWNER", "MANAGER")
def void_order(order_id):
    order = db.session.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.addons))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        from flask import abort
        abort(404)
    reason = request.form.get("reason", "").strip()
    if order.status != "Completed" or len(reason) < 4:
        flash("Enter a cancellation reason (at least 4 characters) for a completed order.", "danger")
        return redirect(url_for("sales.order_detail", order_id=order.id))
    restore_order_stock(order, "Cancellation", reason)
    for payment in order.payments:
        if payment.status == "Recorded":
            payment.status = "Refunded"
            payment.notes = (payment.notes or "") + f" Refund/cancellation: {reason}"
    order.status = "Cancelled"
    order.cancellation_reason = reason
    order.payment_status = "Refunded" if order.payments else "Unpaid"
    audit("Cancelled order", "Order", order.id, reason)
    db.session.commit()
    flash("Order cancelled and stock restored. Recorded payments were marked refunded.", "success")
    return redirect(url_for("sales.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/refund")
@login_required
@role_required("OWNER", "MANAGER")
def refund_order(order_id):
    order = db.session.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.addons))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        from flask import abort
        abort(404)
    reason = request.form.get("reason", "").strip()
    if order.status != "Completed" or len(reason) < 4:
        flash("Enter a refund reason (at least 4 characters) for a completed order.", "danger")
        return redirect(url_for("sales.order_detail", order_id=order.id))
    restore_order_stock(order, "Refund", reason)
    for payment in order.payments:
        if payment.status == "Recorded":
            payment.status = "Refunded"
            payment.notes = (payment.notes or "") + f" Refund: {reason}"
    order.status = "Refunded"
    order.cancellation_reason = reason
    order.payment_status = "Refunded"
    audit("Refunded order", "Order", order.id, reason)
    db.session.commit()
    flash("Order refunded, stock restored, and recorded payments marked refunded.", "success")
    return redirect(url_for("sales.order_detail", order_id=order.id))
