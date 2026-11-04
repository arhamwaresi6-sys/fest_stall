# Festival Food Stall Desk

A private Flask management app for a university festival food stall. It includes team sign-in, products, point of sale, order and payment records, inventory movements, expenses, reports, and a responsive dashboard.

## Start locally

Use Python 3.11 or newer. In PowerShell:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and set a private random `SECRET_KEY`. The example uses a local SQLite database so the app can be opened without a separate database server. The app reads `DATABASE_URL` (or the legacy `SQLALCHEMY_DATABASE_URI`) for database configuration. PostgreSQL and MySQL are also supported; MySQL URLs use the `mysql+pymysql://` dialect.

```text
postgresql+psycopg://stall_user:your-password@localhost:5432/food_stall
```

For a brand-new database, initialize the tables and create the single root account:

```powershell
flask --app run.py init-db
flask --app run.py db upgrade
flask --app run.py check-db
flask --app run.py create-root
python run.py
```

For an existing application database, skip `init-db` and run `flask --app run.py db upgrade` before `check-db` and `create-root`. The migration preserves existing data and enables the new account roles (updating a role check constraint where the database supports it).

Open <http://127.0.0.1:5000> and sign in with the root account. The root command asks for the password without storing it in the source tree.

Anyone can request an account from the sign-in page using a unique username and email. They may sign in using either after ROOT reviews the request from **Team & approvals** and assigns an approved role. ROOT can reject requests, change team access, and cannot be demoted or deactivated through the UI. Keep the root credentials private.

Run the isolated workflow tests with:

```powershell
python -m unittest discover -s tests -v
```

## Roles and approvals

- **Root:** one administrator account with full access, registration approval, and team controls.
- **Manager:** products, POS, inventory, expenses, and reports.
- **Cashier:** POS and order history.
- **Staff:** operational dashboard and stock visibility without financial totals.
- **Owner:** retained only for compatibility with accounts created by older versions; use Root for new installations.

## Payments and sales

The only payment methods are **By hand (cash)** and **bKash**. Payments are entered by the team; the app does not connect to bKash or initiate a transaction. Split payments are supported. Root and managers can apply a fixed-amount or percentage discount at checkout; the server validates the discount, recomputes totals, and allocates discounts in reports. Checkout checks stock, stores product price and cost snapshots, records inventory movement, and saves the order and payments in one database transaction.

Managers can create ingredient stock records from **Inventory → Ingredient inventory**, choosing a unit (piece, g, kg, ml, or L), on-hand quantity, low-stock threshold, and unit cost. Add a product extra in the product form by selecting an ingredient, entering the ingredient quantity used per product, and setting its additional sale price. At checkout, staff can select extras for each cart item; the server recomputes their prices, validates ingredient stock, and deducts both product and ingredient inventory together. Order snapshots preserve the selected extras and costs, and cancellation/refund restores the recorded ingredient quantities.

The dashboard and reports compare products by units sold, net sales revenue after proportional discounts, product and add-on costs, and gross profit for the selected dates. Operating expenses are counted separately in estimated net profit.

## Production notes

- Set `FLASK_DEBUG=0`, a random `SECRET_KEY` of at least 32 characters, and `COOKIE_SECURE=1` when serving over HTTPS.
- Keep `.env` private. Never commit database credentials or production secrets.
- Use the existing Flask-Migrate setup for schema changes: review generated revisions from `flask --app run.py db migrate`, then apply with `db upgrade`. `init-db` is for a new empty database only.
- Run `flask --app run.py check-db` to verify the configured connection and compare all application tables and columns. The app loads `backend/.env` from the project directory even when launched from another working directory.
- Inventory supports searching, filtering by stock health, restock auditing, and a filtered CSV export. Use the dashboard low-stock panel for a quick reorder check.
- Apply pending database revisions with `flask --app run.py db upgrade` before using ingredient inventory and product add-ons.
- Serve behind HTTPS with a production WSGI server such as Gunicorn. Configure backups for the database before festival operations.
- Product photos, stall logos, and receipt images are normalized and kept under the private `backend/instance/uploads/` folder. Back up local uploads with the database. Images are served only through the app’s authenticated route, including role restrictions for receipts.
