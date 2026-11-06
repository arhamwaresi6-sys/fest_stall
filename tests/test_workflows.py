import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import inspect
from werkzeug.datastructures import FileStorage

from project import create_app
from project.extensions import db
from project.food_icons import category_group, food_icon_filename
from project.models import (
    AuditLog,
    Coupon,
    Expense,
    Ingredient,
    IngredientTransaction,
    InventoryTransaction,
    Order,
    OrderItemAddon,
    Payment,
    Product,
    ProductAddon,
    Setting,
    User,
)
from project.utils import (
    expense_amount_between,
    expense_amount_remaining,
    order_item_cost,
)
from settings import Config


class FoodCategoryIconTests(unittest.TestCase):
    def test_food_categories_have_category_groups_and_local_icons(self):
        categories = {
            "burgers": ("Burgers", "burger.svg"),
            " Pizza ": ("Pizza", "pizza.svg"),
            "beverages": ("Drinks", "drink.svg"),
            "desserts": ("Desserts", "cake.svg"),
            "House Special": ("Others", "other.svg"),
        }
        for category, expected in categories.items():
            with self.subTest(category=category):
                self.assertEqual(category_group(category), expected[0])
                self.assertEqual(food_icon_filename(category), expected[1])


class TestConfig(Config):
    TESTING = True
    DEBUG = True
    SECRET_KEY = "workflow-test-secret-key-at-least-32-characters"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False


class WebsiteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        owner = User(username="root", full_name="Test Root", role="ROOT", active=True)
        owner.email = "root@example.test"
        owner.set_password("owner-password-123")
        cashier = User(username="cashier", full_name="Test Cashier", role="CASHIER", active=True)
        cashier.set_password("cashier-password-123")
        product = Product(
            name="Test snack",
            category="Food",
            selling_price=2,
            cost_price=1,
            stock=10,
            min_stock=2,
            is_available=True,
        )
        db.session.add_all([owner, cashier, product])
        db.session.commit()
        self.product_id = product.id
        self.client = self.app.test_client()
        self.login("root", "owner-password-123")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login(self, username, password):
        response = self.client.post(
            "/auth/login", data={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 302)

    def test_owner_get_pages_and_inventory_export(self):
        paths = (
            "/",
            "/dashboard",
            "/overview-guide",
            "/expenses/",
            "/inventory/",
            "/inventory/ingredients",
            "/inventory/?status=low",
            "/inventory/?q=Food",
            "/inventory/export.pdf",
            "/orders",
            "/pos",
            "/coupons",
            "/products/",
            "/products/new",
            "/products/1/edit",
            "/reports/",
            "/reports/products.pdf",
            "/settings",
            "/team/",
            "/team/new",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertLess(self.client.get(path).status_code, 500)

        dashboard = self.client.get("/dashboard")
        self.assertIn(b"viewport-fit=cover", dashboard.data)
        self.assertIn(b"icons.svg#dashboard", dashboard.data)
        icon_sprite = self.client.get("/static/icons.svg")
        self.assertEqual(icon_sprite.status_code, 200)
        self.assertIn(b'id="cart"', icon_sprite.data)
        icon_sprite.close()

        pos_page = self.client.get("/pos").data
        self.assertIn(b"Accepted by", pos_page)
        self.assertIn(b"cashier", pos_page)
        self.assertIn(b"qr_code.svg", pos_page)
        self.assertIn(b"coupon-preview", pos_page)
        qr_response = self.client.get("/static/qr_code.svg")
        self.assertEqual(qr_response.status_code, 200)
        self.assertTrue(qr_response.mimetype.endswith("svg+xml"))
        self.assertIn(b"bKash scan-to-pay QR code", qr_response.data)
        qr_response.close()
        icon_response = self.client.get("/static/bkash-mark.svg")
        self.assertEqual(icon_response.status_code, 200)
        self.assertIn(b"#df146e", icon_response.data)
        icon_response.close()
        pos_script_response = self.client.get("/static/js/pos.js")
        pos_script = pos_script_response.data
        self.assertIn(b"01978327028", pos_script)
        self.assertNotIn("💵".encode("utf-8"), pos_script)
        self.assertNotIn("🅱".encode("utf-8"), pos_script)
        pos_script_response.close()
        self.assertNotIn(b"Customer or order label", pos_page)
        self.assertNotIn(b"Order reference", pos_page)

        response = self.client.get("/inventory/export.pdf")
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("inventory.pdf", response.headers["Content-Disposition"])
        self.assertGreater(len(response.data), 2000)
        self.assertEqual(self.client.get("/inventory/export.csv").status_code, 404)
        self.assertEqual(self.client.get("/reports/products.csv").status_code, 404)

    def test_registration_requires_root_approval(self):
        self.client.post("/auth/logout")
        registration = {
            "full_name": "New Team Member",
            "username": "new.team",
            "email": "new.team@example.test",
            "password": "team-member-password-123",
            "password_confirmation": "team-member-password-123",
        }
        response = self.client.post("/auth/register", data=registration)
        self.assertEqual(response.status_code, 302)
        pending = db.session.scalar(
            db.select(User).where(User.username == "new.team")
        )
        self.assertEqual(pending.role, "PENDING")
        self.assertFalse(pending.active)
        cross_namespace_conflict = dict(
            registration,
            username="different.user",
            email="root",
        )
        response = self.client.post("/auth/register", data=cross_namespace_conflict)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            db.session.scalar(
                db.select(User).where(User.username == "different.user")
            )
        )

        self.client.post("/auth/logout")
        response = self.client.post(
            "/auth/login",
            data={"username": "new.team", "password": registration["password"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"awaiting root approval", response.data)

        self.login("root", "owner-password-123")
        response = self.client.post(
            f"/team/{pending.id}/approve", data={"role": "CASHIER"}
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(pending)
        self.assertEqual(pending.role, "CASHIER")
        self.assertTrue(pending.active)

        self.client.post("/auth/logout")
        self.login("new.team", registration["password"])
        self.assertEqual(self.client.get("/pos").status_code, 200)
        self.assertEqual(self.client.get("/team/").status_code, 403)
        self.client.post("/auth/logout")
        self.login("new.team@example.test", registration["password"])
        self.assertEqual(self.client.get("/pos").status_code, 200)

        self.client.post("/auth/logout")
        self.login("root", "owner-password-123")
        rejected = dict(
            registration,
            username="reject.me",
            email="reject.me@example.test",
        )
        self.client.post("/auth/logout")
        self.client.post("/auth/register", data=rejected)
        rejected_user = db.session.scalar(
            db.select(User).where(User.username == "reject.me")
        )
        self.login("root", "owner-password-123")
        self.assertEqual(
            self.client.post(f"/team/{rejected_user.id}/reject").status_code, 302
        )
        self.assertIsNone(db.session.get(User, rejected_user.id))

    def test_root_checkout_discount_and_single_root_protection(self):
        checkout = {
            "checkout_token": "workflow-discount-1",
            "accepted_by_id": str(
                db.session.scalar(db.select(User).where(User.username == "cashier")).id
            ),
            "cart": json.dumps([{"id": self.product_id, "quantity": 2}]),
            "payments": json.dumps([{"method": "hand", "amount": "3.00"}]),
            "discount": "25",
            "discount_kind": "percent",
        }
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-discount-1")
        )
        self.assertEqual(str(order.discount), "1.00")
        self.assertEqual(str(order.total), "3.00")
        self.assertEqual(order.accepted_by.username, "cashier")
        self.assertEqual(order.created_by.username, "root")

        root = db.session.scalar(db.select(User).where(User.role == "ROOT"))
        self.assertEqual(self.client.post(f"/team/{root.id}/toggle").status_code, 302)
        db.session.refresh(root)
        self.assertTrue(root.active)
        self.assertEqual(
            self.client.post(
                f"/team/{root.id}/edit",
                data={"full_name": "Test Root", "role": "CASHIER"},
            ).status_code,
            302,
        )
        db.session.refresh(root)
        self.assertEqual(root.role, "ROOT")
        self.assertEqual(
            self.client.post(
                "/team/new",
                data={
                    "username": "secondroot",
                    "full_name": "Second Root",
                    "role": "ROOT",
                    "password": "root-password-123",
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(User.id)).where(User.role == "ROOT")
            ),
            1,
        )

    def test_coupon_preview_stacks_and_code_is_consumed_once(self):
        coupon = Coupon(
            code="SAVE25",
            discount_type="percent",
            discount_value=25,
        )
        db.session.add(coupon)
        db.session.commit()
        preview = self.client.post(
            "/pos/coupon-preview",
            data={"code": "save25", "subtotal": "4.00"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["discount_amount"], "1.00")

        cashier = db.session.scalar(db.select(User).where(User.username == "cashier"))
        checkout = {
            "checkout_token": "workflow-coupon-1",
            "accepted_by_id": str(cashier.id),
            "cart": json.dumps([{"id": self.product_id, "quantity": 2}]),
            "payments": json.dumps([{"method": "hand", "amount": "2.00"}]),
            "discount": "25",
            "discount_kind": "percent",
            "coupon_code": "save25",
        }
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-coupon-1")
        )
        self.assertEqual(str(order.discount), "2.00")
        self.assertEqual(str(order.total), "2.00")
        db.session.refresh(coupon)
        self.assertIsNotNone(coupon.redeemed_at)
        self.assertEqual(coupon.redeemed_order_id, order.id)

        preview = self.client.post(
            "/pos/coupon-preview",
            data={"code": "SAVE25", "subtotal": "2.00"},
        )
        self.assertEqual(preview.status_code, 400)
        coupon_page = self.client.get("/coupons")
        self.assertIn(b"SAVE25", coupon_page.data)
        self.assertIn(b"Reset code", coupon_page.data)
        reset_response = self.client.post(f"/coupons/{coupon.id}/reset")
        self.assertEqual(reset_response.status_code, 302)
        db.session.refresh(coupon)
        self.assertIsNone(coupon.redeemed_at)
        self.assertIsNone(coupon.redeemed_order_id)
        preview = self.client.post(
            "/pos/coupon-preview",
            data={"code": "SAVE25", "subtotal": "2.00"},
        )
        self.assertEqual(preview.status_code, 200)
        checkout.update(
            checkout_token="workflow-coupon-2",
            cart=json.dumps([{"id": self.product_id, "quantity": 1}]),
            payments="[]",
        )
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        self.assertIsNotNone(
            db.session.scalar(
                db.select(Coupon.redeemed_at).where(Coupon.id == coupon.id)
            )
        )
        product = db.session.get(Product, self.product_id)
        self.assertEqual(product.stock, 7)

    def test_coupon_management_is_limited_to_financial_roles(self):
        self.client.post("/auth/logout")
        self.login("cashier", "cashier-password-123")
        self.assertEqual(self.client.get("/coupons").status_code, 403)
        self.assertEqual(self.client.post("/coupons/1/reset").status_code, 403)

    def test_dashboard_shows_payment_and_top_revenue_charts(self):
        high_revenue_product = Product(
            name="High Revenue item",
            category="Food",
            selling_price=7,
            cost_price=2,
            stock=5,
            min_stock=1,
            is_available=True,
        )
        db.session.add(high_revenue_product)
        db.session.commit()

        for token, product_id in (
            ("dashboard-low-revenue", self.product_id),
            ("dashboard-high-revenue", high_revenue_product.id),
        ):
            response = self.client.post(
                "/pos",
                data={
                    "checkout_token": token,
                    "cart": json.dumps([{"id": product_id, "quantity": 1}]),
                    "payments": "[]",
                },
            )
            self.assertEqual(response.status_code, 302)

        today = date.today().isoformat()
        dashboard = self.client.get(f"/dashboard?start={today}&end={today}")
        self.assertEqual(dashboard.status_code, 200)
        html = dashboard.data.decode()
        self.assertIn("How customers paid", html)
        self.assertIn("payment-donut", html)
        top_revenue_section = html.split("Top revenue products", 1)[1].split(
            "Product performance", 1
        )[0]
        self.assertLess(
            top_revenue_section.index("High Revenue item"),
            top_revenue_section.index("Test snack"),
        )

    def test_dashboard_spreads_scheduled_expenses_and_shows_all_time_profit(self):
        root_id = db.session.scalar(
            db.select(User.id).where(User.username == "root")
        )
        db.session.add_all(
            [
                Expense(
                    title="Historical equipment",
                    category="Equipment",
                    amount="1000.00",
                    expense_date=date.today() - timedelta(days=5),
                    duration_days=10,
                    created_by_id=root_id,
                ),
                Expense(
                    title="Current packaging",
                    category="Packaging",
                    amount="25.00",
                    expense_date=date.today() - timedelta(days=1),
                    created_by_id=root_id,
                ),
            ]
        )
        db.session.commit()

        today = date.today().isoformat()
        response = self.client.get(f"/dashboard?start={today}&end={today}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Expense still scheduled", response.data)
        self.assertIn(b"400.00", response.data)
        self.assertIn(b"Total expense commitments", response.data)
        self.assertIn(b"1,025.00", response.data)
        self.assertIn(b"Expense cost recognized", response.data)
        self.assertIn(b"100.00", response.data)
        self.assertIn(b"-625.00", response.data)
        self.assertIn(b"-100.00", response.data)
        self.assertIn(b"All-time net profit", response.data)
        self.assertIn(b"Daily expense deductions", response.data)
        self.assertIn(date.today().strftime("%a, %d %b %Y").encode(), response.data)
        self.assertIn(b"Historical equipment", response.data)
        self.assertIn(b"100.00", response.data)

    def test_four_day_expense_schedule_reduces_balance_and_can_make_profit_negative(self):
        root_id = db.session.scalar(
            db.select(User.id).where(User.username == "root")
        )
        today = date.today()
        expense = Expense(
            title="Four day stall booking",
            category="Equipment",
            amount=Decimal("2500.00"),
            expense_date=today - timedelta(days=3),
            duration_days=30,
            created_by_id=root_id,
        )
        db.session.add(expense)
        db.session.commit()

        start = (today - timedelta(days=3)).isoformat()
        end = today.isoformat()
        dashboard = self.client.get(f"/dashboard?start={start}&end={end}")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"How the result is calculated", dashboard.data)
        self.assertIn(b"Scheduled expenses are deducted in full", dashboard.data)
        self.assertIn(b"333.33", dashboard.data)
        self.assertIn(b"-333.33", dashboard.data)
        self.assertIn(b"2,166.67", dashboard.data)

        expenses = self.client.get("/expenses/")
        self.assertEqual(expenses.status_code, 200)
        self.assertIn(b"333.33", expenses.data)
        self.assertIn(b"2,166.67", expenses.data)

    def test_booking_date_is_the_first_scheduled_day(self):
        expense = Expense(
            title="Stall booking",
            category="Equipment",
            amount=Decimal("2500.00"),
            expense_date=date(2026, 11, 4),
            duration_days=30,
        )

        self.assertEqual(
            expense_amount_between(
                [expense], date(2026, 11, 4), date(2026, 11, 4)
            ),
            Decimal("83.33"),
        )
        self.assertEqual(
            expense_amount_between(
                [expense], date(2026, 11, 5), date(2026, 11, 5)
            ),
            Decimal("83.33"),
        )
        self.assertEqual(
            expense_amount_remaining(expense, date(2026, 11, 4)),
            Decimal("2416.67"),
        )
        self.assertEqual(
            expense_amount_remaining(expense, date(2026, 11, 5)),
            Decimal("2333.34"),
        )

    def test_overview_guide_explains_metrics_and_expense_schedule(self):
        response = self.client.get("/overview-guide")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"How to read your overview", response.data)
        self.assertIn(b"Gross profit", response.data)
        self.assertIn(b"Period net profit", response.data)
        self.assertIn(b"2,333.34 remaining", response.data)

    def test_expense_duration_distributes_rounding_cents_and_remaining(self):
        expense = Expense(
            title="Three-day booking",
            category="Equipment",
            amount=Decimal("10.00"),
            expense_date=date(2026, 1, 1),
            duration_days=3,
        )
        daily_costs = [
            expense_amount_between(
                [expense], date(2026, 1, day), date(2026, 1, day)
            )
            for day in range(1, 4)
        ]

        self.assertEqual(
            daily_costs,
            [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")],
        )
        self.assertEqual(sum(daily_costs), Decimal("10.00"))
        self.assertEqual(
            expense_amount_remaining(expense, date(2026, 1, 2)),
            Decimal("3.34"),
        )
        self.assertEqual(
            expense_amount_remaining(expense, date(2025, 12, 31)),
            Decimal("10.00"),
        )

    def test_checkout_rejects_invalid_order_acceptors(self):
        inactive_cashier = User(
            username="inactive.cashier",
            full_name="Inactive Cashier",
            role="CASHIER",
            active=False,
        )
        inactive_cashier.set_password("inactive-cashier-password")
        active_staff = User(
            username="active.staff",
            full_name="Active Staff",
            role="STAFF",
            active=True,
        )
        active_staff.set_password("active-staff-password")
        db.session.add_all([inactive_cashier, active_staff])
        db.session.commit()

        for token, user in (
            ("workflow-inactive-acceptor", inactive_cashier),
            ("workflow-unauthorized-acceptor", active_staff),
        ):
            checkout = {
                "checkout_token": token,
                "accepted_by_id": str(user.id),
                "cart": json.dumps([{"id": self.product_id, "quantity": 1}]),
                "payments": "[]",
            }
            response = self.client.post("/pos", data=checkout)
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                b"Choose an active user who can accept orders.", response.data
            )
            self.assertIsNone(
                db.session.scalar(
                    db.select(Order).where(Order.checkout_token == token)
                )
            )

    def test_product_and_inventory_tracking(self):
        response = self.client.post(
            "/products/new",
            data={
                "name": "New snack",
                "category": "Food",
                "selling_price": "3.25",
                "cost_price": "1.20",
                "stock": "3",
                "min_stock": "4",
                "is_available": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = db.session.scalar(db.select(Product).where(Product.name == "New snack"))
        self.assertIsNotNone(product)
        self.assertEqual(self.client.get("/inventory/?status=low").status_code, 200)
        self.assertIn(b"New snack", self.client.get("/inventory/?q=New").data)

        response = self.client.post(
            "/inventory/adjust",
            data={
                "product_id": product.id,
                "quantity_changed": "5",
                "kind": "Restock",
                "reason": "Weekly supplier restock",
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(product)
        self.assertEqual(product.stock, 8)

        response = self.client.post(
            f"/products/{product.id}/edit",
            data={
                "name": "Updated snack",
                "category": "Food",
                "selling_price": "4.00",
                "cost_price": "1.25",
                "stock": "8",
                "min_stock": "2",
                "is_available": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.post(f"/products/{product.id}/archive").status_code, 302
        )

    def test_product_can_be_hidden_from_sales_and_restored(self):
        response = self.client.post(
            f"/products/{self.product_id}/availability"
        )
        self.assertEqual(response.status_code, 302)
        product = db.session.get(Product, self.product_id)
        self.assertFalse(product.is_available)
        self.assertIn(b"Test snack", self.client.get("/products/").data)
        self.assertNotIn(b"Test snack", self.client.get("/pos").data)

        response = self.client.post(
            f"/products/{self.product_id}/availability"
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(product)
        self.assertTrue(product.is_available)
        self.assertIn(b"Test snack", self.client.get("/pos").data)

    def test_deleting_order_restores_stock_and_removes_order_history(self):
        response = self.client.post(
            "/pos",
            data={
                "checkout_token": "workflow-delete-order",
                "cart": json.dumps([{"id": self.product_id, "quantity": 2}]),
                "payments": json.dumps([{"method": "hand", "amount": "1.00"}]),
                "discount": "0",
                "discount_kind": "amount",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-delete-order")
        )
        order_id = order.id
        order_number = order.order_number
        self.assertEqual(db.session.get(Product, self.product_id).stock, 8)

        response = self.client.post(f"/orders/{order_id}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(Order, order_id))
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(Payment.id)).where(Payment.order_id == order_id)
            ),
            0,
        )
        self.assertEqual(db.session.get(Product, self.product_id).stock, 10)
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(InventoryTransaction.id)).where(
                    InventoryTransaction.order_id == order_id
                )
            ),
            0,
        )
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(InventoryTransaction.id)).where(
                    InventoryTransaction.reason.like(f"Order {order_number}:%")
                )
            ),
            1,
        )

    def test_deleting_product_removes_containing_orders_and_restores_other_stock(self):
        other_product = Product(
            name="Other snack",
            category="Food",
            selling_price=3,
            cost_price=1,
            stock=6,
            min_stock=2,
            is_available=True,
        )
        ingredient = Ingredient(
            name="Deletion test extra",
            unit="piece",
            stock=5,
            min_stock=0,
            unit_cost=0,
            active=True,
        )
        other_product.addons.append(
            ProductAddon(
                ingredient=ingredient,
                quantity_used=1,
                unit_price=0,
            )
        )
        db.session.add_all([other_product, ingredient])
        db.session.commit()
        other_product_id = other_product.id
        response = self.client.post(
            "/pos",
            data={
                "checkout_token": "workflow-delete-product",
                "cart": json.dumps(
                    [
                        {"id": self.product_id, "quantity": 1},
                        {
                            "id": other_product_id,
                            "quantity": 2,
                            "addons": [ingredient.id],
                        },
                    ]
                ),
                "payments": json.dumps([{"method": "hand", "amount": "8.00"}]),
                "discount": "0",
                "discount_kind": "amount",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-delete-product")
        )
        order_id = order.id

        response = self.client.post(f"/products/{self.product_id}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(Product, self.product_id))
        self.assertIsNone(db.session.get(Order, order_id))
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(Payment.id)).where(Payment.order_id == order_id)
            ),
            0,
        )
        self.assertEqual(db.session.get(Product, other_product_id).stock, 6)
        self.assertEqual(db.session.get(Ingredient, ingredient.id).stock, 5)
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(InventoryTransaction.id)).where(
                    InventoryTransaction.product_id == self.product_id
                )
            ),
            0,
        )

    def test_delete_foreign_keys_cascade_in_database_schema(self):
        inspector = inspect(db.engine)
        expected = {
            ("order_item", "order_id"): "CASCADE",
            ("order_item", "product_id"): "SET NULL",
            ("payment", "order_id"): "CASCADE",
            ("inventory_transaction", "product_id"): "CASCADE",
            ("inventory_transaction", "order_id"): "CASCADE",
            ("ingredient_transaction", "order_id"): "CASCADE",
            ("product_addon", "product_id"): "CASCADE",
            ("order_item_addon", "order_item_id"): "CASCADE",
        }
        for (table, column), ondelete in expected.items():
            with self.subTest(table=table, column=column):
                foreign_key = next(
                    foreign_key
                    for foreign_key in inspector.get_foreign_keys(table)
                    if foreign_key["constrained_columns"] == [column]
                )
                self.assertEqual(foreign_key["options"].get("ondelete"), ondelete)

    def test_ingredient_inventory_forms_and_stock_validation(self):
        response = self.client.post(
            "/inventory/ingredients",
            data={
                "name": "Page style test ingredient",
                "unit": "g",
                "stock": "5.000",
                "min_stock": "1.000",
                "unit_cost": "0.1250",
            },
        )
        self.assertEqual(response.status_code, 302)
        ingredient = db.session.scalar(
            db.select(Ingredient).where(
                Ingredient.name == "Page style test ingredient"
            )
        )
        self.assertIsNotNone(ingredient)

        response = self.client.post(
            f"/inventory/ingredients/{ingredient.id}/details",
            data={"unit_cost": "0.2500", "min_stock": "2.000"},
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(ingredient)
        self.assertEqual(str(ingredient.unit_cost), "0.2500")
        self.assertEqual(str(ingredient.min_stock), "2.000")

        response = self.client.post(
            f"/inventory/ingredients/{ingredient.id}/adjust",
            data={
                "kind": "Damaged",
                "quantity_changed": "-1.500",
                "reason": "Damaged during storage",
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(ingredient)
        self.assertEqual(str(ingredient.stock), "3.500")

        response = self.client.post(
            f"/inventory/ingredients/{ingredient.id}/adjust",
            data={
                "kind": "Damaged",
                "quantity_changed": "-4.000",
                "reason": "Damaged during storage",
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(ingredient)
        self.assertEqual(str(ingredient.stock), "3.500")

        page = self.client.get("/inventory/ingredients")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"ingredient-create-form", page.data)
        self.assertIn(b"ingredient-edit-form", page.data)
        self.assertIn(b"ingredient-adjust-form", page.data)
        self.assertIn(b"Damaged during storage", page.data)

    def test_sale_payment_refund_and_void(self):
        checkout = {
            "checkout_token": "workflow-checkout-1",
            "accepted_by_id": str(
                db.session.scalar(db.select(User).where(User.username == "root")).id
            ),
            "cart": json.dumps([{"id": self.product_id, "quantity": 1}]),
            "payments": json.dumps([{"method": "hand", "amount": "1.00"}]),
            "discount": "0",
            "discount_kind": "amount",
        }
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-checkout-1")
        )
        self.assertEqual(order.payment_status, "Partially paid")
        self.assertEqual(self.client.get(f"/orders/{order.id}").status_code, 200)
        self.assertEqual(
            self.client.post(
                f"/orders/{order.id}/payments",
                data={"method": "bkash", "amount": "1.00"},
            ).status_code,
            302,
        )
        db.session.refresh(order)
        self.assertEqual(order.payment_status, "Paid")
        self.assertEqual(
            self.client.post(
                f"/orders/{order.id}/refund", data={"reason": "Customer returned item"}
            ).status_code,
            302,
        )
        db.session.refresh(order)
        self.assertEqual(order.status, "Refunded")

        checkout.update(
            checkout_token="workflow-checkout-2",
            payments="[]",
        )
        self.assertEqual(self.client.post("/pos", data=checkout).status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == "workflow-checkout-2")
        )
        self.assertEqual(
            self.client.post(
                f"/orders/{order.id}/void", data={"reason": "Customer cancelled"}
            ).status_code,
            302,
        )
        db.session.refresh(order)
        self.assertEqual(order.status, "Cancelled")

    def test_product_performance_pdf_includes_completed_sales(self):
        response = self.client.post(
            "/pos",
            data={
                "checkout_token": "workflow-product-performance-pdf",
                "cart": json.dumps([{"id": self.product_id, "quantity": 2}]),
                "payments": "[]",
                "discount": "0",
                "discount_kind": "amount",
            },
        )
        self.assertEqual(response.status_code, 302)
        report_date = date.today().isoformat()
        response = self.client.get(
            f"/reports/products.pdf?start={report_date}&end={report_date}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn(report_date, response.headers["Content-Disposition"])
        self.assertGreater(len(response.data), 2000)

    def test_product_addons_are_priced_tracked_and_restored(self):
        response = self.client.post(
            "/inventory/ingredients",
            data={
                "name": "Extra tomato",
                "unit": "piece",
                "stock": "5",
                "min_stock": "1",
                "unit_cost": "0.1250",
            },
        )
        self.assertEqual(response.status_code, 302)
        ingredient = db.session.scalar(
            db.select(Ingredient).where(Ingredient.name == "Extra tomato")
        )
        self.assertIsNotNone(ingredient)
        self.assertEqual(str(ingredient.stock), "5.000")

        response = self.client.post(
            "/products/new",
            data={
                "name": "Addon burger",
                "category": "Burgers",
                "description": "",
                "selling_price": "4.00",
                "cost_price": "2.00",
                "stock": "4",
                "min_stock": "1",
                "is_available": "on",
                "addon_ingredient_id": str(ingredient.id),
                "addon_quantity": "1.500",
                "addon_price": "0.75",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = db.session.scalar(
            db.select(Product).where(Product.name == "Addon burger")
        )
        self.assertEqual(len(product.addons), 1)
        self.assertEqual(str(product.addons[0].quantity_used), "1.500")
        response = self.client.post(
            f"/products/{product.id}/edit",
            data={
                "name": "Addon burger",
                "category": "Burgers",
                "description": "",
                "selling_price": "4.00",
                "cost_price": "2.00",
                "stock": str(product.stock),
                "min_stock": "1",
                "is_available": "on",
                "addon_ingredient_id": str(ingredient.id),
                "addon_quantity": "1.500",
                "addon_price": "0.75",
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(product)
        self.assertEqual(len(product.addons), 1)

        checkout_token = "addon-workflow-checkout"
        response = self.client.post(
            "/pos",
            data={
                "checkout_token": checkout_token,
                "accepted_by_id": str(
                    db.session.scalar(
                        db.select(User).where(User.username == "cashier")
                    ).id
                ),
                "cart": json.dumps(
                    [{"id": product.id, "quantity": 2, "addons": [ingredient.id]}]
                ),
                "payments": "[]",
                "discount": "0",
                "discount_kind": "amount",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = db.session.scalar(
            db.select(Order).where(Order.checkout_token == checkout_token)
        )
        item = order.items[0]
        self.assertEqual(str(order.subtotal), "9.50")
        self.assertEqual(str(item.line_total), "9.50")
        self.assertEqual(len(item.addons), 1)
        self.assertIsInstance(item.addons[0], OrderItemAddon)
        self.assertEqual(item.addons[0].ingredient_name, "Extra tomato")
        self.assertEqual(order_item_cost(item), Decimal("4.375000"))
        self.assertEqual(str(ingredient.stock), "2.000")
        self.assertEqual(product.stock, 2)

        response = self.client.get(f"/orders/{order.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Extras: Extra tomato", response.data)

        response = self.client.post(
            f"/orders/{order.id}/void", data={"reason": "Customer cancelled"}
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(ingredient)
        db.session.refresh(product)
        self.assertEqual(str(ingredient.stock), "5.000")
        self.assertEqual(product.stock, 4)
        self.assertEqual(
            db.session.scalar(
                db.select(db.func.count(IngredientTransaction.id)).where(
                    IngredientTransaction.order_id == order.id,
                    IngredientTransaction.kind == "Cancellation",
                )
            ),
            1,
        )

    def test_checkout_rejects_addons_when_ingredient_stock_is_short(self):
        ingredient = Ingredient(
            name="Limited cheese",
            unit="g",
            stock=1,
            min_stock=0,
            unit_cost="0.2500",
        )
        product = db.session.get(Product, self.product_id)
        product.addons.append(
            ProductAddon(ingredient=ingredient, quantity_used="2.000", unit_price="0.50")
        )
        db.session.add(ingredient)
        db.session.commit()
        response = self.client.post(
            "/pos",
            data={
                "checkout_token": "addon-insufficient-stock",
                "accepted_by_id": str(
                    db.session.scalar(
                        db.select(User).where(User.username == "cashier")
                    ).id
                ),
                "cart": json.dumps(
                    [{"id": product.id, "quantity": 1, "addons": [ingredient.id]}]
                ),
                "payments": "[]",
                "discount": "0",
                "discount_kind": "amount",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Not enough Limited cheese", response.data)
        self.assertIsNone(
            db.session.scalar(
                db.select(Order).where(
                    Order.checkout_token == "addon-insufficient-stock"
                )
            )
        )
        db.session.refresh(product)
        db.session.refresh(ingredient)
        self.assertEqual(product.stock, 10)
        self.assertEqual(str(ingredient.stock), "1.000")

    def test_expenses_settings_team_and_reports(self):
        data = {
            "title": "Test expense",
            "category": "Miscellaneous",
            "amount": "5.25",
            "expense_date": date.today().isoformat(),
            "duration_days": "3",
            "description": "Workflow check",
        }
        self.assertEqual(self.client.post("/expenses/new", data=data).status_code, 302)
        expense = db.session.scalar(
            db.select(Expense).where(Expense.title == "Test expense")
        )
        self.assertEqual(expense.duration_days, 3)
        data.update(title="Updated expense", amount="6.25", duration_days="10")
        self.assertEqual(
            self.client.post(f"/expenses/{expense.id}/edit", data=data).status_code, 302
        )
        db.session.refresh(expense)
        self.assertEqual(expense.duration_days, 10)
        expenses_page = self.client.get("/expenses/")
        self.assertEqual(expenses_page.status_code, 200)
        self.assertIn(b"Total committed", expenses_page.data)
        self.assertIn(b"Charged to profit", expenses_page.data)
        self.assertIn(b"Spread", expenses_page.data)
        self.assertEqual(
            self.client.post(
                "/settings",
                data={
                    "stall_name": "Workflow Stall",
                    "contact_info": "",
                    "receipt_footer": "",
                    "currency": "Tk",
                    "festival_open": "",
                    "festival_close": "",
                    "low_stock_threshold": "5",
                },
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                "/team/new",
                data={
                    "username": "newmanager",
                    "full_name": "New Manager",
                    "role": "MANAGER",
                    "password": "manager-password-123",
                },
            ).status_code,
            302,
        )
        manager = db.session.scalar(
            db.select(User).where(User.username == "newmanager")
        )
        self.assertEqual(
            self.client.post(
                f"/team/{manager.id}/edit",
                data={"full_name": "Updated Manager", "role": "MANAGER"},
            ).status_code,
            302,
        )
        self.assertEqual(self.client.get("/reports/").status_code, 200)
        report_pdf = self.client.get("/reports/products.pdf")
        self.assertEqual(report_pdf.mimetype, "application/pdf")
        self.assertTrue(report_pdf.data.startswith(b"%PDF-"))
        self.assertIn("product-performance-", report_pdf.headers["Content-Disposition"])
        self.assertGreater(len(report_pdf.data), 2000)
        self.assertEqual(db.session.get(Setting, "stall_name").value, "Workflow Stall")

    def test_expense_entry_supports_one_time_and_spread_allocation(self):
        response = self.client.get("/expenses/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"All at once", response.data)
        self.assertIn(b"Spread across multiple days", response.data)

        one_time = self.client.post(
            "/expenses/new",
            data={
                "title": "One-time permit",
                "category": "Miscellaneous",
                "amount": "40.00",
                "expense_date": date.today().isoformat(),
                "allocation_type": "once",
            },
        )
        self.assertEqual(one_time.status_code, 302)
        expense = db.session.scalar(
            db.select(Expense).where(Expense.title == "One-time permit")
        )
        self.assertEqual(expense.duration_days, 1)

        invalid_spread = self.client.post(
            "/expenses/new",
            data={
                "title": "Invalid spread",
                "category": "Miscellaneous",
                "amount": "40.00",
                "expense_date": date.today().isoformat(),
                "allocation_type": "spread",
                "duration_days": "1",
            },
        )
        self.assertEqual(invalid_spread.status_code, 200)
        self.assertIsNone(
            db.session.scalar(
                db.select(Expense).where(Expense.title == "Invalid spread")
            )
        )

    def test_expense_delete_is_audited_and_removes_receipt(self):
        root_id = db.session.scalar(
            db.select(User.id).where(User.username == "root")
        )
        expense = Expense(
            title="Expense to delete",
            category="Packaging",
            amount="12.50",
            description="Remove after checking receipt",
            expense_date=date.today(),
            created_by_id=root_id,
            receipt_filename="receipts/test-expense-delete.jpg",
        )
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id
        receipt_path = (
            Path(self.app.instance_path)
            / "uploads"
            / "receipts"
            / "test-expense-delete.jpg"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes(b"test receipt")

        response = self.client.post(f"/expenses/{expense_id}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(Expense, expense_id))
        self.assertFalse(receipt_path.exists())
        audit_event = db.session.scalar(
            db.select(AuditLog).where(
                AuditLog.action == "Deleted expense",
                AuditLog.entity_id == str(expense_id),
            )
        )
        self.assertIsNotNone(audit_event)
        self.assertIn("Expense to delete", audit_event.details)

    def test_expense_delete_requires_manager_role(self):
        root_id = db.session.scalar(
            db.select(User.id).where(User.username == "root")
        )
        expense = Expense(
            title="Protected expense",
            category="Packaging",
            amount="12.50",
            expense_date=date.today(),
            created_by_id=root_id,
        )
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id

        self.client.post("/auth/logout")
        self.login("cashier", "cashier-password-123")
        response = self.client.post(f"/expenses/{expense_id}/delete")

        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(db.session.get(Expense, expense_id))

    def test_report_separates_lifetime_and_period_expenses(self):
        root_id = db.session.scalar(
            db.select(User.id).where(User.username == "root")
        )
        db.session.add_all(
            [
                Expense(
                    title="Historical equipment",
                    category="Equipment",
                    amount="1000.00",
                    expense_date=date(2000, 1, 1),
                    created_by_id=root_id,
                ),
                Expense(
                    title="Current packaging",
                    category="Packaging",
                    amount="25.00",
                    expense_date=date.today(),
                    created_by_id=root_id,
                ),
            ]
        )
        db.session.commit()

        response = self.client.get(
            f"/reports/?start={date.today().isoformat()}&end={date.today().isoformat()}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"All-time expenses", response.data)
        self.assertIn(b"1,025.00", response.data)
        self.assertIn(b"1,000.00", response.data)
        self.assertIn(b"Expense cost recognized", response.data)
        self.assertIn(b"25.00", response.data)
        self.assertIn(b"-25.00", response.data)

    def test_cashier_permissions_and_private_receipts(self):
        self.client.post("/auth/logout")
        self.login("cashier", "cashier-password-123")
        self.assertEqual(self.client.get("/orders").status_code, 200)
        self.assertEqual(self.client.get("/expenses/").status_code, 403)
        self.assertEqual(
            self.client.get(
                "/uploads/receipts/" + "a" * 32 + ".jpg"
            ).status_code,
            403,
        )

    def test_local_image_upload_and_authenticated_delivery(self):
        image_bytes = BytesIO()
        Image.new("RGB", (12, 12), "red").save(image_bytes, format="PNG")
        image_bytes.seek(0)
        from project.image_uploads import save_image

        path = save_image(
            FileStorage(stream=image_bytes, filename="test.png"), "products"
        )
        self.assertRegex(path, r"^products/[a-f0-9]{32}\.jpg$")
        image_path = Path(self.app.instance_path) / "uploads" / path
        response = None
        try:
            response = self.client.get(f"/uploads/{path}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/jpeg")
            self.assertGreater(len(response.data), 0)
        finally:
            if response is not None:
                response.close()
            image_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
