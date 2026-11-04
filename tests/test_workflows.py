import json
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import FileStorage

from project import create_app
from project.extensions import db
from project.models import Expense, Order, Product, Setting, User
from settings import Config


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
            "/expenses/",
            "/inventory/",
            "/inventory/?status=low",
            "/inventory/?q=Food",
            "/inventory/export.csv",
            "/orders",
            "/pos",
            "/products/",
            "/products/new",
            "/products/1/edit",
            "/reports/",
            "/reports/products.csv",
            "/settings",
            "/team/",
            "/team/new",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertLess(self.client.get(path).status_code, 500)

        pos_page = self.client.get("/pos").data
        self.assertIn(b"Accepted by", pos_page)
        self.assertIn(b"cashier", pos_page)
        self.assertNotIn(b"Customer or order label", pos_page)
        self.assertNotIn(b"Order reference", pos_page)

        response = self.client.get("/inventory/export.csv")
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn(b"Test snack", response.data)

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

    def test_expenses_settings_team_and_reports(self):
        data = {
            "title": "Test expense",
            "category": "Miscellaneous",
            "amount": "5.25",
            "expense_date": date.today().isoformat(),
            "description": "Workflow check",
        }
        self.assertEqual(self.client.post("/expenses/new", data=data).status_code, 302)
        expense = db.session.scalar(
            db.select(Expense).where(Expense.title == "Test expense")
        )
        data.update(title="Updated expense", amount="6.25")
        self.assertEqual(
            self.client.post(f"/expenses/{expense.id}/edit", data=data).status_code, 302
        )
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
        self.assertEqual(self.client.get("/reports/products.csv").mimetype, "text/csv")
        self.assertEqual(db.session.get(Setting, "stall_name").value, "Workflow Stall")

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
