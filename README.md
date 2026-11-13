# Festival Food Stall Desk

A private Flask management app for a university festival food stall. It includes team sign-in, products, point of sale, order and payment records, inventory movements, expenses, reports, and a responsive dashboard.

Food category illustrations are locally served Twemoji SVGs, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Artwork source: [Twemoji](https://github.com/twitter/twemoji).

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

To enable Google sign-in locally, create an OAuth 2.0 **Web application** client in Google Cloud Console. For a local server at `http://127.0.0.1:5000`, add `http://127.0.0.1:5000` as an Authorized JavaScript origin and `http://127.0.0.1:5000/auth/google/callback` as an Authorized redirect URI. Add the client ID and secret to `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; keep the default Google discovery URL and set `GOOGLE_REDIRECT_URI` to that callback URL. Use a separate OAuth client for local development and production. Do not expose the client secret in frontend code.

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

For an existing application database, skip `init-db` and run `flask --app run.py db upgrade` before `check-db` and `create-root`. Migrations preserve existing records while updating account roles and delete-related foreign-key behavior.

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

The only payment methods are **By hand (cash)** and **bKash**. At checkout, the selected method is saved as the customer's preferred method; the order stays **Unpaid** until a team member uses **Mark paid** on the Orders page. That action records the outstanding balance using the saved method. Selecting a method or displaying the bKash QR code does not record a payment or connect to bKash. The QR code is served from `project/static/qr_code.svg`, with the local brand mark at `project/static/bkash-mark.svg` (source: `https://raw.githubusercontent.com/HckrXyzz/image/main/bkash.svg`). Root and managers can apply a fixed-amount or percentage discount at checkout; staff can also apply a coupon code. Coupon discounts stack with staff discounts, and each code can be redeemed once. Root and managers can review codes on **Coupons** and reset redeemed codes for reuse. The `coupon` table is created by the latest migration. Checkout validates coupons and totals again before consuming a code, and saves the order, stock changes, and coupon redemption in one database transaction. Payment is recorded separately when marked paid from Orders.

Root and managers can permanently delete orders; completed orders return their product and ingredient stock. Permanently deleting a product also deletes every order containing it, including mixed-product orders and their payments, and restores stock for the remaining items. Use **Hide from sales** to temporarily remove a product from the POS while keeping its product record and sales history.

Managers can create ingredient stock records from **Inventory → Ingredient inventory**, choosing a unit (piece, g, kg, ml, or L), on-hand quantity, low-stock threshold, and unit cost. Add a product extra in the product form by selecting an ingredient, entering the ingredient quantity used per product, and setting its additional sale price. At checkout, staff can select extras for each cart item; the server recomputes their prices, validates ingredient stock, and deducts both product and ingredient inventory together. Order snapshots preserve the selected extras and costs, and cancellation/refund restores the recorded ingredient quantities.

The dashboard and reports compare products by units sold, net sales revenue after proportional discounts, product and add-on costs, and gross profit for the selected dates. Expense records distinguish the full committed amount from cost recognized against profit: choose a one-time deduction or allocate the amount evenly across a duration, starting on the recorded date. Rounding cents are distributed so the schedule exactly matches the committed amount. Period net profit subtracts the cost allocated to that period; all-time net profit subtracts recognized costs to date, while the remaining scheduled balance is shown separately. Existing expenses retain their saved dates and durations. Managers can delete expense records from the expense list; deletions are audited and attached receipt files are removed.

Inventory and product-performance downloads are landscape PDFs with red-and-white styling, period/filter context, summary totals, detailed tables, and page numbers. Inventory PDFs use the current inventory filters; product-performance PDFs use the selected report dates.

## Production notes

- Set `FLASK_DEBUG=0`, a random `SECRET_KEY` of at least 32 characters, and `COOKIE_SECURE=1` when serving over HTTPS.
- In Cloud Run, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_DISCOVERY_URL=https://accounts.google.com/.well-known/openid-configuration`, and `GOOGLE_REDIRECT_URI=https://fest-stall-980361887314.europe-west1.run.app/auth/google/callback`. Configure the matching Google Cloud Console Authorized JavaScript origin as `https://fest-stall-980361887314.europe-west1.run.app` and Authorized redirect URI as `https://fest-stall-980361887314.europe-west1.run.app/auth/google/callback`. Store the client secret in Secret Manager and expose it to the Cloud Run revision as an environment variable. Keep `COOKIE_SECURE=1`.
- After deploying Google sign-in, apply its additive user-table migration with `flask --app run.py db upgrade` (or run the same migration as a deployment step) before serving requests. Existing users and password hashes are preserved. New Google accounts remain inactive and require root approval, matching the existing registration policy.
- Keep `.env` private. Never commit database credentials or production secrets.
- Use the existing Flask-Migrate setup for schema changes: review generated revisions from `flask --app run.py db migrate`, then apply with `db upgrade`. `init-db` is for a new empty database only.
- Before deploying the saved-payment-method update, run `flask --app run.py db upgrade` from `backend` against the production database, then run `flask --app run.py check-db`. This applies revision `20261113_paymethod`, which adds `order.payment_method`; do not serve the updated app against the old schema.
- Run `flask --app run.py check-db` to verify the configured connection and compare all application tables and columns. The app loads `backend/.env` from the project directory even when launched from another working directory.
- Inventory supports searching, filtering by stock health, restock auditing, and a filtered CSV export. Use the dashboard low-stock panel for a quick reorder check.
- Apply pending database revisions with `flask --app run.py db upgrade` before using ingredient inventory and product add-ons.
- Serve behind HTTPS with a production WSGI server such as Gunicorn. Configure backups for the database before festival operations.
- Product photos, stall logos, and receipt images are normalized and kept under the private `backend/instance/uploads/` folder. Back up local uploads with the database. Images are served only through the app’s authenticated route, including role restrictions for receipts.
