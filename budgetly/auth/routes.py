import re
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import UserMixin, current_user, login_required, login_user, logout_user
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from config import (
    CATEGORY_GROUPS,
    CURRENCY_SYMBOLS,
    EMAIL_PATTERN,
    GROUP_LABELS,
    INCOME_PAYMENT_METHODS,
    PAYMENT_METHODS,
    SPECIAL_CHARS,
)
from database import get_db, get_user_settings, save_user_settings


LOGIN_ATTEMPTS = {}


class User(UserMixin):
    def __init__(self, id, username, email=None):
        self.id = id
        self.username = username
        self.email = email


def validate_password(password, username=None):
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least 1 uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least 1 lowercase letter.")
    if not re.search(r"[0-9]", password):
        errors.append("Password must contain at least 1 number.")
    if not any(ch in SPECIAL_CHARS for ch in password):
        errors.append(f"Password must contain at least 1 special character ({' '.join(SPECIAL_CHARS)}).")
    if " " in password:
        errors.append("Password cannot contain spaces.")
    if username and username.strip().lower() in password.lower():
        errors.append("Password cannot contain your username.")
    return errors


def is_password_previously_used(conn, user_id, password):
    rows = conn.execute(
        "SELECT password_hash FROM password_history WHERE user_id = ?", (user_id,)
    ).fetchall()
    return any(check_password_hash(row["password_hash"], password) for row in rows)


def record_password(conn, user_id, password_hash):
    conn.execute(
        "INSERT INTO password_history (user_id, password_hash, created_at) VALUES (?, ?, ?)",
        (user_id, password_hash, datetime.utcnow().isoformat()),
    )


def register_routes(app, login_manager, mail, reset_serializer):
    @login_manager.user_loader
    def load_user(user_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if row:
            return User(row["id"], row["username"], row["email"])
        return None

    def login_key():
        return f"{request.remote_addr}:{request.form.get('username', '').strip().lower()}"

    def login_is_limited():
        item = LOGIN_ATTEMPTS.get(login_key())
        if not item:
            return False
        return item["count"] >= 5 and (datetime.utcnow() - item["first"]).total_seconds() < 900

    def record_login_failure():
        key = login_key()
        now = datetime.utcnow()
        item = LOGIN_ATTEMPTS.get(key)
        if not item or (now - item["first"]).total_seconds() >= 900:
            LOGIN_ATTEMPTS[key] = {"count": 1, "first": now}
        else:
            item["count"] += 1

    def clear_login_failures():
        LOGIN_ATTEMPTS.pop(login_key(), None)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not username or not email or not password:
                flash("Please fill in all fields.")
                return redirect(url_for("register"))
            if password != confirm_password:
                flash("Passwords do not match.")
                return redirect(url_for("register"))
            if not EMAIL_PATTERN.match(email):
                flash("Please enter a valid email address.")
                return redirect(url_for("register"))
            errors = validate_password(password, username)
            if errors:
                for error in errors:
                    flash(error)
                return redirect(url_for("register"))

            conn = get_db()
            if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                conn.close()
                flash("That username is already taken.")
                return redirect(url_for("register"))
            if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                conn.close()
                flash("That email is already registered.")
                return redirect(url_for("register"))

            password_hash = generate_password_hash(password)
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, password_hash),
            )
            user_id = cursor.lastrowid
            record_password(conn, user_id, password_hash)
            conn.execute(
                "INSERT OR IGNORE INTO user_settings (user_id, updated_at) VALUES (?, ?)",
                (user_id, datetime.utcnow().isoformat()),
            )
            conn.commit()
            conn.close()
            flash("Account created! Please log in.")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if login_is_limited():
                flash("Too many failed attempts. Please wait 15 minutes and try again.")
                return redirect(url_for("login"))
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            conn = get_db()
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            conn.close()
            if row and check_password_hash(row["password_hash"], password):
                clear_login_failures()
                login_user(User(row["id"], row["username"], row["email"]))
                return redirect(url_for("dashboard"))
            record_login_failure()
            flash("Invalid username or password.")
            return redirect(url_for("login"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            conn = get_db()
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            conn.close()
            if row and row["email"]:
                token = reset_serializer.dumps(
                    {"email": row["email"], "hash": row["password_hash"]},
                    salt="password-reset-salt",
                )
                reset_url = url_for("reset_password", token=token, _external=True)
                try:
                    message = Message(
                        "Reset your Budgetly password", recipients=[row["email"]]
                    )
                    message.body = (
                        "We received a request to reset your Budgetly password.\n\n"
                        f"Click the link below to choose a new one (expires in 1 hour):\n{reset_url}\n\n"
                        "If you did not request this, you can safely ignore this email."
                    )
                    mail.send(message)
                except Exception:
                    app.logger.exception("Failed to send password reset email")
            flash("If that email is registered, we've sent a link to reset your password.")
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        try:
            data = reset_serializer.loads(token, salt="password-reset-salt", max_age=3600)
            email, token_hash = data["email"], data["hash"]
        except SignatureExpired:
            flash("That reset link has expired. Please request a new one.")
            return redirect(url_for("forgot_password"))
        except BadSignature:
            flash("That reset link is invalid.")
            return redirect(url_for("forgot_password"))

        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or row["password_hash"] != token_hash:
            conn.close()
            flash("That reset link is invalid or has already been used.")
            return redirect(url_for("forgot_password"))
        if request.method == "POST":
            new_password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if new_password != confirm_password:
                conn.close()
                flash("Passwords do not match.")
                return redirect(url_for("reset_password", token=token))
            errors = validate_password(new_password, row["username"])
            if not errors and is_password_previously_used(conn, row["id"], new_password):
                errors.append("You've used that password before. Please choose a different one.")
            if errors:
                conn.close()
                for error in errors:
                    flash(error)
                return redirect(url_for("reset_password", token=token))
            new_hash = generate_password_hash(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["id"]))
            record_password(conn, row["id"], new_hash)
            conn.commit()
            conn.close()
            flash("Your password has been reset. Please log in.")
            return redirect(url_for("login"))
        conn.close()
        return render_template("reset_password.html", token=token, username=row["username"])

    @app.route("/settings")
    @login_required
    def settings():
        return render_template(
            "settings.html", user_settings=get_user_settings(current_user.id),
            currencies=CURRENCY_SYMBOLS, category_groups=CATEGORY_GROUPS,
            group_labels=GROUP_LABELS, payment_methods=PAYMENT_METHODS,
        )

    @app.route("/settings/profile", methods=["POST"])
    @login_required
    def update_profile():
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not username or not EMAIL_PATTERN.match(email):
            flash("Please enter a valid username and email.")
            return redirect(url_for("settings"))
        conn = get_db()
        duplicate = conn.execute(
            "SELECT id FROM users WHERE (username = ? OR email = ?) AND id != ?",
            (username, email, current_user.id),
        ).fetchone()
        if duplicate:
            conn.close()
            flash("That username or email is already in use.")
            return redirect(url_for("settings"))
        conn.execute(
            "UPDATE users SET username = ?, email = ? WHERE id = ?",
            (username, email, current_user.id),
        )
        conn.commit()
        conn.close()
        current_user.username = username
        current_user.email = email
        flash("Profile updated.")
        return redirect(url_for("settings"))

    @app.route("/settings/password", methods=["POST"])
    @login_required
    def change_password():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        conn = get_db()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (current_user.id,)
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password):
            conn.close()
            flash("Your current password is incorrect.")
            return redirect(url_for("settings"))
        errors = []
        if new_password != confirm_password:
            errors.append("Passwords do not match.")
        errors.extend(validate_password(new_password, current_user.username))
        if not errors and is_password_previously_used(conn, current_user.id, new_password):
            errors.append("You've used that password before. Please choose a different one.")
        if errors:
            conn.close()
            for error in errors:
                flash(error)
            return redirect(url_for("settings"))
        new_hash = generate_password_hash(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, current_user.id))
        record_password(conn, current_user.id, new_hash)
        conn.commit()
        conn.close()
        flash("Password updated.")
        return redirect(url_for("settings"))

    @app.route("/settings/preferences", methods=["POST"])
    @login_required
    def update_preferences():
        settings = get_user_settings(current_user.id)
        currency = request.form.get("currency", "PHP")
        default_group = request.form.get("default_group", "variable_expense")
        default_category = request.form.get("default_category", "")
        payment_method = request.form.get("default_payment_method", "Cash")
        week_start = request.form.get("week_start", "monday")
        try:
            threshold = int(request.form.get("budget_alert_threshold", 80))
        except ValueError:
            threshold = 80
        if currency not in CURRENCY_SYMBOLS:
            currency = "PHP"
        if default_group not in CATEGORY_GROUPS:
            default_group = "variable_expense"
        if default_category not in CATEGORY_GROUPS[default_group]:
            default_category = CATEGORY_GROUPS[default_group][0]
        if payment_method not in PAYMENT_METHODS:
            payment_method = "Cash"
        if week_start not in ("monday", "sunday"):
            week_start = "monday"
        if threshold not in (50, 80, 100):
            threshold = 80
        save_user_settings(current_user.id, {
            **settings, "currency": currency, "default_group": default_group,
            "default_category": default_category, "default_payment_method": payment_method,
            "week_start": week_start, "budget_alert_threshold": threshold,
            "compact_mode": bool(request.form.get("compact_mode")),
        })
        flash("Preferences saved.")
        return redirect(url_for("settings"))

    @app.route("/settings/notifications", methods=["POST"])
    @login_required
    def update_notifications():
        settings = get_user_settings(current_user.id)
        save_user_settings(current_user.id, {
            **settings, "budget_alerts": bool(request.form.get("budget_alerts")),
            "weekly_summary": bool(request.form.get("weekly_summary")),
            "goal_reminders": bool(request.form.get("goal_reminders")),
        })
        flash("Notification preferences saved.")
        return redirect(url_for("settings"))

    @app.route("/settings/data/export.csv")
    @login_required
    def export_user_csv():
        import csv
        import io
        from flask import Response

        conn = get_db()
        rows = conn.execute(
            "SELECT date, group_name, category, amount, payment_method, description "
            "FROM transactions WHERE user_id = ? ORDER BY date, id",
            (current_user.id,),
        ).fetchall()
        conn.close()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "group_name", "category", "amount", "payment_method", "description"])
        for row in rows:
            writer.writerow([
                row["date"], row["group_name"], row["category"],
                row["amount"], row["payment_method"], row["description"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=budgetly-transactions.csv"},
        )

    @app.route("/settings/data/backup.json")
    @login_required
    def download_backup():
        import json
        from flask import Response

        conn = get_db()
        transactions = [dict(row) for row in conn.execute(
            "SELECT * FROM transactions WHERE user_id = ?", (current_user.id,)
        )]
        goals = [dict(row) for row in conn.execute(
            "SELECT * FROM goals WHERE user_id = ?", (current_user.id,)
        )]
        budgets = [dict(row) for row in conn.execute(
            "SELECT * FROM budgets WHERE user_id = ?", (current_user.id,)
        )]
        conn.close()
        backup = {
            "version": 1,
            "exported_at": datetime.utcnow().isoformat(),
            "profile": {"username": current_user.username, "email": current_user.email},
            "settings": get_user_settings(current_user.id),
            "transactions": transactions,
            "goals": goals,
            "budgets": budgets,
        }
        return Response(
            json.dumps(backup, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=budgetly-backup.json"},
        )

    @app.route("/settings/data/import", methods=["POST"])
    @login_required
    def import_transactions():
        import csv
        import io

        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename.lower().endswith(".csv"):
            flash("Please choose a CSV file.")
            return redirect(url_for("settings"))
        try:
            content = uploaded.stream.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            required = {"date", "group_name", "category", "amount"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                flash("CSV must include date, group_name, category, and amount columns.")
                return redirect(url_for("settings"))
            conn = get_db()
            imported = skipped = 0
            for row in reader:
                if imported + skipped >= 5000:
                    break
                group_name = (row.get("group_name") or "").strip()
                category = (row.get("category") or "").strip()
                payment_method = (row.get("payment_method") or "").strip()
                transaction_date = (row.get("date") or "").strip()
                try:
                    amount = float(row.get("amount", 0))
                except (TypeError, ValueError):
                    amount = 0
                if (
                    group_name not in CATEGORY_GROUPS
                    or category not in CATEGORY_GROUPS[group_name]
                    or payment_method
                    and payment_method not in (
                        INCOME_PAYMENT_METHODS if group_name == "income" else PAYMENT_METHODS
                    )
                    or amount <= 0
                ):
                    skipped += 1
                    continue
                try:
                    datetime.strptime(transaction_date, "%Y-%m-%d")
                except ValueError:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO transactions "
                    "(user_id, group_name, category, description, amount, payment_method, date) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        current_user.id, group_name, category,
                        (row.get("description") or "").strip()[:200],
                        amount, payment_method, transaction_date,
                    ),
                )
                imported += 1
            conn.commit()
            conn.close()
            flash(
                f"Imported {imported} transaction(s)"
                + (f"; skipped {skipped} invalid row(s)." if skipped else ".")
            )
        except UnicodeDecodeError:
            flash("The CSV file must be UTF-8 encoded.")
        return redirect(url_for("settings"))

    @app.route("/settings/delete-account", methods=["POST"])
    @login_required
    def delete_account():
        password = request.form.get("password", "")
        confirmation = request.form.get("delete_confirmation", "")
        conn = get_db()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (current_user.id,)
        ).fetchone()
        if (
            confirmation != "DELETE"
            or not row
            or not check_password_hash(row["password_hash"], password)
        ):
            conn.close()
            flash("Account deletion requires the correct password and DELETE confirmation.")
            return redirect(url_for("settings"))
        conn.execute("DELETE FROM users WHERE id = ?", (current_user.id,))
        conn.commit()
        conn.close()
        logout_user()
        flash("Your account has been deleted.")
        return redirect(url_for("login"))
