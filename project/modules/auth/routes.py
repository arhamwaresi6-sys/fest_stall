import re
import secrets
from collections.abc import Mapping
from urllib.parse import urlsplit

from authlib.integrations.base_client.errors import OAuthError
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from joserfc.errors import JoseError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...extensions import db
from ...models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,80}$")


def _google_client():
    if not current_app.config["GOOGLE_CLIENT_ID"] or not current_app.config["GOOGLE_CLIENT_SECRET"]:
        return None
    return current_app.extensions["google_oauth"].create_client("google")


def _google_redirect_uri():
    return current_app.config["GOOGLE_REDIRECT_URI"] or url_for(
        "auth.google_callback", _external=True
    )


def _google_picture_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    return value if parts.scheme == "https" and parts.netloc else None


def _google_username(email):
    stem = re.sub(r"[^a-z0-9._-]+", ".", email.split("@", 1)[0].lower())
    stem = stem.strip("._-")[:70].strip("._-") or "google.user"
    if len(stem) < 3:
        stem = f"g.{stem}"
    suffix = 0
    while True:
        username = stem if suffix == 0 else f"{stem}.{suffix}"
        if db.session.scalar(
            select(User.id).where(
                db.or_(
                    db.func.lower(User.username) == username,
                    db.func.lower(User.email) == username,
                    db.func.lower(User.username) == email,
                )
            )
        ) is None:
            return username
        suffix += 1


def _google_sign_in_error(message):
    flash(message, "danger")
    return redirect(url_for("auth.login"))


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


@bp.get("/google")
def google_login():
    client = _google_client()
    if client is None:
        return _google_sign_in_error("Google sign-in is not configured yet.")
    try:
        return client.authorize_redirect(
            _google_redirect_uri(), code_challenge_method="S256"
        )
    except (OAuthError, OSError):
        return _google_sign_in_error("Google sign-in is temporarily unavailable. Please try again.")


@bp.get("/google/callback")
def google_callback():
    client = _google_client()
    if client is None:
        return _google_sign_in_error("Google sign-in is not configured yet.")

    try:
        # Authlib validates the ID-token signature, nonce, issuer, audience, and expiry.
        token = client.authorize_access_token()
    except OAuthError:
        if request.args.get("error") == "access_denied":
            return _google_sign_in_error("Google sign-in was cancelled.")
        return _google_sign_in_error("Google sign-in could not be verified. Please try again.")
    except (JoseError, OSError, ValueError, TypeError):
        return _google_sign_in_error("Google returned an invalid sign-in response. Please try again.")

    claims = token.get("userinfo") if isinstance(token, Mapping) else None
    if not isinstance(claims, Mapping):
        return _google_sign_in_error("Google returned an invalid sign-in response. Please try again.")

    subject = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    full_name = claims.get("name")
    email = email.strip() if isinstance(email, str) else ""
    if (
        not isinstance(subject, str)
        or not subject
        or len(email) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        or email_verified is not True
    ):
        return _google_sign_in_error("Google did not provide a verified email address.")

    email = email.lower()
    user = db.session.scalar(select(User).where(User.google_sub == subject))
    if user is None:
        matching_users = db.session.scalars(
            select(User).where(db.func.lower(User.email) == email).limit(2)
        ).all()
        if len(matching_users) > 1:
            return _google_sign_in_error(
                "More than one account uses this email. Please contact the root user."
            )
        user = matching_users[0] if matching_users else None
        if user is not None and user.google_sub not in (None, subject):
            return _google_sign_in_error(
                "That email is already linked to a different Google account."
            )
        if user is None:
            name = full_name.strip() if isinstance(full_name, str) else ""
            if not name:
                name = email.split("@", 1)[0]
            user = User(
                username=_google_username(email),
                email=email,
                full_name=name[:120],
                role="PENDING",
                active=False,
                google_sub=subject,
                google_picture_url=_google_picture_url(claims.get("picture")),
            )
            user.set_password(secrets.token_urlsafe(48))
            db.session.add(user)
        else:
            user.google_sub = subject
            if not user.google_picture_url:
                user.google_picture_url = _google_picture_url(claims.get("picture"))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _google_sign_in_error(
                "This Google account could not be linked because the email or identity is already in use."
            )

    if user.role == "PENDING" or not user.active:
        if user.role == "PENDING":
            return _google_sign_in_error(
                "Your account is awaiting root approval before you can sign in."
            )
        return _google_sign_in_error("This account has been disabled.")

    login_user(user)
    return redirect(url_for("main.dashboard"))


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
