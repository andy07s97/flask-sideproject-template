# app/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from .models import db, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Basic email + password registration."""
    if request.method == "GET":
        return render_template("register.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("auth.register"))

    existing = User.query.filter_by(email=email).first()
    if existing:
        flash("This email is already registered.", "error")
        return redirect(url_for("auth.register"))

    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    flash("Account created. You are now logged in.", "success")
    return redirect(url_for("main.index"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Basic email + password login."""
    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    login_user(user)
    flash("Logged in successfully.", "success")
    return redirect(url_for("main.index"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Log the current user out."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/account")
@login_required
def account():
    """Simple example account page."""
    return render_template("account.html", user=current_user)
