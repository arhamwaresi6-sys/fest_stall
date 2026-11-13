import os
from datetime import datetime
from zoneinfo import ZoneInfo

import click
from authlib.integrations.flask_client import OAuth
from flask import Flask, g, render_template
from flask_login import current_user
from sqlalchemy import inspect, select

from settings import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    app.config["DEBUG"] = os.getenv("FLASK_DEBUG", str(app.config.get("DEBUG", False))).strip().lower() in {"1", "true", "yes", "on"}
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", app.config["SECRET_KEY"])
    if not app.config["DEBUG"] and (len(app.config["SECRET_KEY"]) < 32 or app.config["SECRET_KEY"].startswith("replace-with")):
        raise RuntimeError("Set a random SECRET_KEY of at least 32 characters in the backend .env file before starting outside debug mode.")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

    from . import models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    oauth = OAuth(app)
    app.extensions["google_oauth"] = oauth
    if app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]:
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=app.config["GOOGLE_DISCOVERY_URL"],
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
            },
        )

    from .modules.auth.routes import bp as auth_bp
    from .modules.main.routes import bp as main_bp
    from .modules.products.routes import bp as products_bp
    from .modules.sales.routes import bp as sales_bp
    from .modules.inventory.routes import bp as inventory_bp
    from .modules.expenses.routes import bp as expenses_bp
    from .modules.reports.routes import bp as reports_bp
    from .modules.team.routes import bp as team_bp

    for blueprint in (auth_bp, main_bp, products_bp, sales_bp, inventory_bp, expenses_bp, reports_bp, team_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, title="That area is owner-only",
                               message="Your account does not have access to this area."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, title="We can’t find that page",
                               message="The page may have moved, or the link may be out of date."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code=413, title="That file is too large",
                               message="Choose a smaller file and try again."), 413

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("error.html", code=500, title="Something went wrong",
                               message="The request could not be completed. Please try again."), 500

    @app.template_filter("money")
    def money(value):
        from decimal import Decimal
        if not hasattr(g, "_money_currency"):
            from .models import Setting
            row = db.session.get(Setting, "currency")
            g._money_currency = row.value if row and row.value.strip() else app.config.get("CURRENCY", "৳")
        return f"{g._money_currency}{Decimal(value or 0):,.2f}"

    @app.template_filter("dhaka")
    def dhaka(value):
        if value is None:
            return "—"
        try:
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo("UTC"))
            return value.astimezone(ZoneInfo("Asia/Dhaka")).strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return str(value)

    @app.template_filter("food_icon")
    def food_icon(category):
        from .food_icons import food_icon_filename
        return food_icon_filename(category)

    @app.context_processor
    def inject_shell_values():
        return {
            "now": datetime.now(ZoneInfo("Asia/Dhaka")),
            "active_user": current_user,
            "google_oauth_enabled": bool(
                app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]
            ),
        }

    def schema_issues(require_all_tables=True):
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        issues = []
        for name, table in sorted(db.metadata.tables.items()):
            if name not in existing_tables:
                if require_all_tables:
                    issues.append(f"Missing table: {name}")
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(name)}
            expected_columns = set(table.columns.keys())
            missing_columns = sorted(expected_columns - existing_columns)
            extra_columns = sorted(existing_columns - expected_columns)
            if missing_columns or extra_columns:
                details = []
                if missing_columns:
                    details.append(f"missing columns: {', '.join(missing_columns)}")
                if extra_columns:
                    details.append(f"unexpected columns: {', '.join(extra_columns)}")
                issues.append(f"Incompatible table {name} ({'; '.join(details)})")
            if name == "user":
                role_checks = inspector.get_check_constraints(name)
                role_check = next(
                    (check for check in role_checks if check["name"] == "ck_user_role_allowed"),
                    None,
                )
                role_check_sql = (role_check or {}).get("sqltext") or ""
                if role_check and not {"ROOT", "PENDING"}.issubset(role_check_sql.upper()):
                    issues.append(
                        "Incompatible table user (role constraint lacks ROOT/PENDING; run "
                        "flask --app run.py db upgrade)"
                    )
        return issues

    @app.cli.command("check-db")
    def check_db():
        """Check database connectivity and verify the schema matches the app."""
        from sqlalchemy import text

        db.session.execute(text("SELECT 1"))
        issues = schema_issues()
        if issues:
            raise click.ClickException(
                "The configured database schema does not match this app:\n- "
                + "\n- ".join(issues)
                + "\nUse the correct DATABASE_URL/SQLALCHEMY_DATABASE_URI, then run "
                "flask --app run.py init-db for a new empty database or apply migrations."
            )
        click.echo("Database connection and application schema are healthy.")
        from .models import User
        if not db.session.scalar(select(User.id).where(User.role == "ROOT", User.active.is_(True))):
            click.echo("No active root account exists yet. Create one with: flask --app run.py create-root")

    @app.cli.command("init-db")
    def init_db():
        """Create tables for a new installation. Prefer migrations after the initial setup."""
        issues = schema_issues(require_all_tables=False)
        if issues:
            raise click.ClickException(
                "Refusing to modify incompatible existing tables:\n- "
                + "\n- ".join(issues)
                + "\nPoint the app at the correct database or migrate the existing schema."
            )
        db.create_all()
        issues = schema_issues()
        if issues:
            raise click.ClickException("Database initialization was incomplete:\n- " + "\n- ".join(issues))
        click.echo("Database tables are ready and match the application models.")

    @app.cli.command("create-root")
    def create_root():
        """Create the first root account interactively."""
        import getpass
        from .models import User
        from sqlalchemy import select
        if db.session.scalar(select(User.id).where(User.role == "ROOT")):
            print("A root account already exists.")
            return
        username = input("Root username: ").strip().lower()
        if not username or len(username) > 80:
            print("Enter a username between 1 and 80 characters.")
            return
        email = input("Root email: ").strip().lower()
        if not email or len(email) > 254 or "@" not in email:
            print("Enter a valid email address.")
            return
        if db.session.scalar(
            select(User.id).where(
                db.or_(
                    db.func.lower(User.username) == username,
                    db.func.lower(User.email) == email,
                )
            )
        ):
            print("That username or email is already in use.")
            return
        full_name = input("Root full name: ").strip() or username
        if len(full_name) > 120:
            print("The root full name cannot exceed 120 characters.")
            return
        password = getpass.getpass("Root password (11-128 characters): ")
        if len(password) < 11 or len(password) > 128:
            print("Password must have 11-128 characters.")
            return
        root = User(username=username, email=email, full_name=full_name, role="ROOT", active=True)
        root.set_password(password)
        db.session.add(root)
        db.session.commit()
        print("Root account created.")

    @app.cli.command("create-owner")
    def create_owner():
        """Deprecated compatibility command for older deployment instructions."""
        click.echo("Use 'flask --app run.py create-root' to set up the root account.")

    return app
