from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
import re

from ...extensions import db
from ...models import User
from ...utils import audit, role_required

bp = Blueprint("team", __name__, url_prefix="/team")
ROLES = ["OWNER", "MANAGER", "CASHIER", "STAFF"]
APPROVABLE_ROLES = ["MANAGER", "CASHIER", "STAFF"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.get("/")
@login_required
@role_required("ROOT")
def index():
    users = db.session.scalars(select(User).order_by(User.role, User.full_name)).all()
    return render_template("team/index.html", users=users, approvable_roles=APPROVABLE_ROLES)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("ROOT")
def create():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower() or None
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "CASHIER")
        if not username or len(username) > 80 or not full_name or role not in ROLES or len(password) < 12 or len(password) > 128:
            flash("Enter a username, full name, role, and password with at least 12 characters.", "danger")
        elif email and (len(email) > 254 or not EMAIL_PATTERN.fullmatch(email)):
            flash("Enter a valid email address.", "danger")
        elif db.session.scalar(
            select(User.id).where(
                db.or_(
                    db.func.lower(User.username) == username,
                    db.func.lower(User.email) == email if email else db.false(),
                    db.func.lower(User.email) == username,
                    db.func.lower(User.username) == email if email else db.false(),
                )
            )
        ):
            flash("That username or email is already in use.", "danger")
        else:
            user = User(username=username, email=email, full_name=full_name[:120], role=role, active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            audit("Created team member", "User", user.id, f"{user.username} ({role})")
            db.session.commit()
            flash("Team member created.", "success")
            return redirect(url_for("team.index"))
    return render_template("team/form.html", roles=ROLES, user=None)


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("ROOT")
def edit(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == "PENDING":
        flash("Approve or reject this registration before editing its access.", "danger")
        return redirect(url_for("team.index"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower() or None
        role = user.role if user.role == "ROOT" else request.form.get("role", "")
        password = request.form.get("password", "")
        if not full_name or (email and (len(email) > 254 or not EMAIL_PATTERN.fullmatch(email))) or (user.role != "ROOT" and role not in ROLES):
            flash("Enter a full name and choose a valid role.", "danger")
        elif email and db.session.scalar(
            select(User.id).where(
                db.or_(
                    db.func.lower(User.email) == email,
                    db.func.lower(User.username) == email,
                ),
                User.id != user.id,
            )
        ):
            flash("That email address is already in use.", "danger")
        elif password and len(password) < 12:
            flash("A new password must have at least 12 characters.", "danger")
        else:
            old_role = user.role
            user.full_name = full_name[:120]
            user.email = email
            user.role = role
            if password:
                user.set_password(password)
            audit("Updated team member", "User", user.id, f"Role {old_role} → {role}")
            db.session.commit()
            flash("Team member updated.", "success")
            return redirect(url_for("team.index"))
    return render_template("team/form.html", roles=ROLES, user=user)


@bp.post("/<int:user_id>/toggle")
@login_required
@role_required("ROOT")
def toggle(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
    elif user.role == "ROOT":
        flash("The root account cannot be deactivated.", "danger")
    elif user.role == "PENDING":
        flash("Use the registration review actions to approve or reject this account.", "danger")
    else:
        user.active = not user.active
        audit("Changed team member access", "User", user.id, f"Active={user.active}")
        db.session.commit()
        flash("Team member access updated.", "success")
    return redirect(url_for("team.index"))


@bp.post("/<int:user_id>/approve")
@login_required
@role_required("ROOT")
def approve(user_id):
    user = db.get_or_404(User, user_id)
    role = request.form.get("role", "STAFF")
    if user.role != "PENDING" or user.active:
        flash("That registration is no longer waiting for approval.", "danger")
    elif role not in APPROVABLE_ROLES:
        flash("Choose a valid team role before approving.", "danger")
    else:
        user.role = role
        user.active = True
        audit("Approved registration", "User", user.id, f"{user.username} ({role})")
        db.session.commit()
        flash(f"{user.full_name} can now sign in as {role.title()}.", "success")
    return redirect(url_for("team.index"))


@bp.post("/<int:user_id>/reject")
@login_required
@role_required("ROOT")
def reject(user_id):
    user = db.get_or_404(User, user_id)
    if user.role != "PENDING" or user.active:
        flash("Only registrations awaiting approval can be rejected.", "danger")
    else:
        username = user.username
        audit("Rejected registration", "User", user.id, username)
        db.session.delete(user)
        db.session.commit()
        flash(f"Registration for {username} was rejected.", "success")
    return redirect(url_for("team.index"))
