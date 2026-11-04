import re
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...extensions import db
from ...models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,80}$")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        identifier = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(
            select(User).where(
                db.or_(
                    db.func.lower(User.username) == identifier,
                    db.func.lower(User.email) == identifier,
                )
            )
        )
        if user and user.check_password(password):
            if user.role == "PENDING" or not user.active:
                flash("Your account is awaiting root approval or has been disabled.", "info")
            else:
                login_user(user, remember=request.form.get("remember") == "on")
                target = request.args.get("next", "")
                parts = urlsplit(target)
                if target and not parts.netloc and not parts.scheme and target.startswith("/"):
                    return redirect(target)
                return redirect(url_for("main.dashboard"))
        else:
            flash("Those sign-in details were not recognized.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        if not USERNAME_PATTERN.fullmatch(username):
            flash("Choose a username with 3–80 letters, numbers, dots, underscores, or hyphens.", "danger")
        elif not full_name or len(full_name) > 120:
            flash("Enter your full name (up to 120 characters).", "danger")
        elif len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "danger")
        elif len(password) < 12 or len(password) > 128:
            flash("Choose a password between 12 and 128 characters.", "danger")
        elif password != confirmation:
            flash("The passwords do not match.", "danger")
        elif db.session.scalar(
            select(User.id).where(
                db.or_(
                    db.func.lower(User.username) == username,
                    db.func.lower(User.email) == email,
                    db.func.lower(User.email) == username,
                    db.func.lower(User.username) == email,
                )
            )
        ):
            flash("That username or email is already in use.", "danger")
        else:
            user = User(username=username, email=email, full_name=full_name, role="PENDING", active=False)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("That username or email is already in use. Please choose another.", "danger")
            else:
                flash("Registration submitted. You can sign in after the root user approves your account.", "success")
                return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("You are signed out.", "success")
    return redirect(url_for("auth.login"))
