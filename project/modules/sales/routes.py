import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ...extensions import db
from ...models import InventoryTransaction, Order, OrderItem, Payment, Product
from ...utils import FINANCIAL_ROLES, PAYMENT_METHODS, audit, date_window, decimal_value, parse_date, refresh_order_payment_status, role_required

bp = Blueprint("sales", __name__)


def restore_order_stock(order, kind, reason):
    quantities = {}
    for item in order.items:
        if item.product_id is not None:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
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


@bp.route("/pos", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def pos():
    if request.method == "POST":
        try:
            checkout_token = request.form.get("checkout_token", "").strip()
            if not checkout_token:
                raise ValueError("This checkout form expired. Please review your cart and try again.")
            existing = db.session.scalar(select(Order).where(Order.checkout_token == checkout_token))
            if existing:
                flash("This order was already saved.", "success")
                return redirect(url_for("sales.order_detail", order_id=existing.id))
            cart = json.loads(request.form.get("cart", "[]"))
            payment_rows = json.loads(request.form.get("payments", "[]"))
            if not isinstance(cart, list) or not cart:
                raise ValueError("Add at least one product to the cart.")
            quantities = {}
            for row in cart:
                product_id = int(row.get("id"))
                quantity = int(row.get("quantity"))
                if quantity < 1 or quantity > 999:
                    raise ValueError("Each quantity must be between 1 and 999.")
                quantities[product_id] = quantities.get(product_id, 0) + quantity
            product_rows = db.session.scalars(select(Product).where(Product.id.in_(sorted(quantities))).order_by(Product.id).with_for_update()).all()
            by_id = {product.id: product for product in product_rows}
            if set(by_id) != set(quantities):
                raise ValueError("One of the selected products is no longer available.")
            for product_id, quantity in quantities.items():
                product = by_id[product_id]
                if product.is_archived or not product.is_available:
                    raise ValueError(f"{product.name} is not available for sale.")
                if product.stock < quantity:
                    raise ValueError(f"Not enough stock for {product.name}; only {product.stock} left.")
            subtotal = sum((by_id[pid].selling_price * qty for pid, qty in quantities.items()), Decimal("0.00"))
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
            if not isinstance(payment_rows, list):
                raise ValueError("Payment details are invalid.")
            valid_payments = []
            for payment in payment_rows:
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
                          customer_name=request.form.get("customer_name", "").strip()[:120] or None,
                          reference=request.form.get("reference", "").strip()[:120] or None,
                          notes=request.form.get("notes", "").strip()[:2000] or None,
                          created_by_id=current_user.id)
            db.session.add(order)
            db.session.flush()
            for product_id, quantity in quantities.items():
                product = by_id[product_id]
                order.items.append(OrderItem(product_id=product.id, product_name=product.name,
                                              unit_price=product.selling_price, unit_cost=product.cost_price,
                                              quantity=quantity, line_total=product.selling_price * quantity))
                previous = product.stock
                product.stock -= quantity
                db.session.add(InventoryTransaction(product_id=product.id, previous_quantity=previous,
                                                    quantity_changed=-quantity, new_quantity=product.stock,
                                                    kind="Sale", reason=f"Order {order.order_number}",
                                                    user_id=current_user.id, order_id=order.id))
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
    products = db.session.scalars(select(Product).where(Product.is_archived.is_(False), Product.is_available.is_(True), Product.stock > 0).order_by(Product.category, Product.name)).all()
    categories = sorted({p.category for p in products})
    return render_template("sales/pos.html", products=products, categories=categories, payment_methods=PAYMENT_METHODS,
                           checkout_token=secrets.token_urlsafe(32))


@bp.get("/orders")
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def orders():
    statement = select(Order).order_by(Order.created_at.desc())
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
    order = db.get_or_404(Order, order_id)
    received = sum((p.amount for p in order.payments if p.status == "Recorded"), Decimal("0.00"))
    remaining = max(Decimal("0.00"), order.total - received)
    return render_template("orders/detail.html", order=order, received=received, remaining=remaining,
                           payment_methods=PAYMENT_METHODS, payment_names=PAYMENT_METHODS)


@bp.post("/orders/<int:order_id>/payments")
@login_required
@role_required("OWNER", "MANAGER", "CASHIER")
def add_payment(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
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
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
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
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
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
