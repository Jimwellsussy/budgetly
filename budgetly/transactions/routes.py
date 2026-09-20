import re
from datetime import date, datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from config import CATEGORY_GROUPS, GROUP_LABELS, INCOME_PAYMENT_METHODS, PAYMENT_METHODS
from database import get_db, get_user_settings


def parse_amount(value):
    try:
        amount = float(value)
        return amount if amount > 0 else 0
    except (TypeError, ValueError):
        return 0


def valid_transaction(group_name, category, payment_method=None):
    if group_name not in CATEGORY_GROUPS or category not in CATEGORY_GROUPS[group_name]:
        return False
    allowed = INCOME_PAYMENT_METHODS if group_name == "income" else PAYMENT_METHODS
    return not payment_method or payment_method in allowed


def get_month_transactions(user_id, month):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND date LIKE ? ORDER BY date DESC, id DESC",
        (user_id, f"{month}%"),
    ).fetchall()
    conn.close()
    return rows


def summarize(transactions):
    totals = {"income": 0, "fixed_expense": 0, "variable_expense": 0, "savings": 0}
    category_totals = {}
    for transaction in transactions:
        group = transaction["group_name"]
        if group not in totals:
            continue
        totals[group] += transaction["amount"]
        if group in ("fixed_expense", "variable_expense"):
            category_totals[transaction["category"]] = (
                category_totals.get(transaction["category"], 0) + transaction["amount"]
            )
    return totals, category_totals


def process_recurring_transactions(user_id):
    current_month = date.today().strftime("%Y-%m")
    today_number = date.today().day
    conn = get_db()
    recurring = conn.execute(
        "SELECT * FROM recurring_transactions "
        "WHERE user_id = ? AND active = 1 AND day_of_month <= ?",
        (user_id, today_number),
    ).fetchall()
    for item in recurring:
        if item["last_processed_month"] == current_month:
            continue
        transaction_date = f"{current_month}-{min(item['day_of_month'], 28):02d}"
        conn.execute(
            "INSERT INTO transactions "
            "(user_id, group_name, category, description, amount, payment_method, date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, item["group_name"], item["category"], item["description"],
                item["amount"], item["payment_method"], transaction_date,
            ),
        )
        conn.execute(
            "UPDATE recurring_transactions SET last_processed_month = ? WHERE id = ?",
            (current_month, item["id"]),
        )
    conn.commit()
    conn.close()


def register_routes(app):
    @app.route("/transactions")
    @login_required
    def transactions():
        process_recurring_transactions(current_user.id)
        settings = get_user_settings(current_user.id)
        q = request.args.get("q", "").strip()
        group = request.args.get("group", "").strip()
        category = request.args.get("category", "").strip()
        from_date = request.args.get("from_date", "").strip()
        to_date = request.args.get("to_date", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        where = ["user_id = ?"]
        params = [current_user.id]
        if q:
            where.append("(description LIKE ? OR category LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if group in CATEGORY_GROUPS:
            where.append("group_name = ?")
            params.append(group)
        all_categories = {item for values in CATEGORY_GROUPS.values() for item in values}
        if category in all_categories:
            where.append("category = ?")
            params.append(category)
        if from_date:
            where.append("date >= ?")
            params.append(from_date)
        if to_date:
            where.append("date <= ?")
            params.append(to_date)

        clause = " AND ".join(where)
        conn = get_db()
        total = conn.execute(
            f"SELECT COUNT(*) FROM transactions WHERE {clause}", params
        ).fetchone()[0]
        per_page = 20
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        rows = conn.execute(
            f"SELECT * FROM transactions WHERE {clause} "
            "ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        recurring_rows = conn.execute(
            "SELECT * FROM recurring_transactions "
            "WHERE user_id = ? AND active = 1 ORDER BY day_of_month, id",
            (current_user.id,),
        ).fetchall()
        conn.close()

        default_group = (
            settings["default_group"]
            if settings["default_group"] in CATEGORY_GROUPS
            else "variable_expense"
        )
        default_category = settings["default_category"]
        if default_category not in CATEGORY_GROUPS[default_group]:
            default_category = CATEGORY_GROUPS[default_group][0]
        transaction_defaults = {
            "group": default_group,
            "category": default_category,
            "payment_method": settings["default_payment_method"],
        }
        return render_template(
            "transactions.html",
            transactions=rows,
            total_transactions=total,
            total_pages=total_pages,
            page=page,
            filters={
                "q": q,
                "group": group,
                "category": category,
                "from_date": from_date,
                "to_date": to_date,
            },
            all_categories=sorted(all_categories),
            category_groups=CATEGORY_GROUPS,
            group_labels=GROUP_LABELS,
            payment_methods=PAYMENT_METHODS,
            income_payment_methods=INCOME_PAYMENT_METHODS,
            transaction_defaults=transaction_defaults,
            recurring_transactions=recurring_rows,
            today=date.today().isoformat(),
        )

    @app.route("/transactions/add", methods=["POST"])
    @login_required
    def add_transaction():
        group_name = request.form.get("group_name", "")
        category = request.form.get("category", "")
        amount = parse_amount(request.form.get("amount"))
        payment_method = request.form.get("payment_method", "")
        transaction_date = request.form.get("date", "")
        description = request.form.get("description", "").strip()[:200]
        if (
            not valid_transaction(group_name, category, payment_method)
            or not amount
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction_date)
        ):
            flash("Please check the transaction details and try again.")
            return redirect(url_for("transactions"))
        conn = get_db()
        conn.execute(
            "INSERT INTO transactions "
            "(user_id, group_name, category, description, amount, payment_method, date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                current_user.id, group_name, category, description,
                amount, payment_method, transaction_date,
            ),
        )
        conn.commit()
        conn.close()
        flash("Transaction added.")
        return redirect(url_for("transactions"))

    @app.route("/transactions/edit/<int:transaction_id>", methods=["GET", "POST"])
    @login_required
    def edit_transaction(transaction_id):
        conn = get_db()
        transaction = conn.execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, current_user.id),
        ).fetchone()
        conn.close()
        if not transaction:
            flash("Transaction not found.")
            return redirect(url_for("transactions"))
        if request.method == "POST":
            group_name = request.form.get("group_name", "")
            category = request.form.get("category", "")
            amount = parse_amount(request.form.get("amount"))
            payment_method = request.form.get("payment_method", "")
            transaction_date = request.form.get("date", "")
            description = request.form.get("description", "").strip()[:200]
            if (
                not valid_transaction(group_name, category, payment_method)
                or not amount
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction_date)
            ):
                flash("Please check the transaction details and try again.")
                return redirect(url_for("edit_transaction", transaction_id=transaction_id))
            conn = get_db()
            conn.execute(
                "UPDATE transactions SET group_name = ?, category = ?, description = ?, "
                "amount = ?, payment_method = ?, date = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    group_name, category, description, amount, payment_method,
                    transaction_date, transaction_id, current_user.id,
                ),
            )
            conn.commit()
            conn.close()
            flash("Transaction updated.")
            return redirect(url_for("transactions"))
        return render_template(
            "edit_transaction.html",
            transaction=transaction,
            category_groups=CATEGORY_GROUPS,
            group_labels=GROUP_LABELS,
            payment_methods=PAYMENT_METHODS,
            income_payment_methods=INCOME_PAYMENT_METHODS,
        )

    @app.route("/transactions/delete/<int:transaction_id>", methods=["POST"])
    @login_required
    def delete_transaction(transaction_id):
        conn = get_db()
        conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, current_user.id),
        )
        conn.commit()
        conn.close()
        flash("Transaction deleted.")
        return redirect(url_for("transactions"))

    @app.route("/transactions/recurring/add", methods=["POST"])
    @login_required
    def add_recurring_transaction():
        group_name = request.form.get("group_name", "")
        category = request.form.get("category", "")
        payment_method = request.form.get("payment_method", "")
        amount = parse_amount(request.form.get("amount"))
        description = request.form.get("description", "").strip()[:200]
        try:
            day_of_month = int(request.form.get("day_of_month", 1))
        except (TypeError, ValueError):
            day_of_month = 0
        if (
            not valid_transaction(group_name, category, payment_method)
            or not amount
            or not 1 <= day_of_month <= 28
        ):
            flash("Please check the recurring transaction details.")
            return redirect(url_for("transactions"))
        conn = get_db()
        conn.execute(
            "INSERT INTO recurring_transactions "
            "(user_id, group_name, category, description, amount, payment_method, "
            "day_of_month, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                current_user.id, group_name, category, description, amount,
                payment_method, day_of_month, datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Recurring transaction saved.")
        return redirect(url_for("transactions"))

    @app.route("/transactions/recurring/delete/<int:recurring_id>", methods=["POST"])
    @login_required
    def delete_recurring_transaction(recurring_id):
        conn = get_db()
        conn.execute(
            "UPDATE recurring_transactions SET active = 0 "
            "WHERE id = ? AND user_id = ?",
            (recurring_id, current_user.id),
        )
        conn.commit()
        conn.close()
        flash("Recurring transaction removed.")
        return redirect(url_for("transactions"))
