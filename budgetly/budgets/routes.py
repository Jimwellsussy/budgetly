import re
from datetime import date

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from config import CATEGORY_GROUPS
from database import get_db, get_user_settings
from transactions.routes import get_month_transactions, summarize


def valid_month(value):
    return bool(value and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value))


def get_budget_progress(user_id, month, threshold):
    conn = get_db()
    budgets = conn.execute(
        "SELECT * FROM budgets WHERE user_id = ? AND month = ? ORDER BY category",
        (user_id, month),
    ).fetchall()
    conn.close()
    _, actual_by_category = summarize(get_month_transactions(user_id, month))
    result = []
    for budget in budgets:
        actual = actual_by_category.get(budget["category"], 0)
        amount = budget["budget_amount"]
        percentage = actual / amount * 100 if amount else 0
        result.append({
            "id": budget["id"],
            "category": budget["category"],
            "budget": amount,
            "actual": actual,
            "difference": amount - actual,
            "percentage": round(percentage, 1),
            "progress": min(100, max(0, percentage)),
            "status": (
                "over" if percentage > 100
                else "warning" if percentage >= threshold
                else "ok"
            ),
        })
    return result


def register_routes(app):
    @app.route("/budget", methods=["GET", "POST"])
    @login_required
    def budget():
        selected_month = request.values.get("month", date.today().strftime("%Y-%m"))
        if not valid_month(selected_month):
            selected_month = date.today().strftime("%Y-%m")
        settings = get_user_settings(current_user.id)
        threshold = int(settings["budget_alert_threshold"])

        if request.method == "POST":
            category = request.form.get("category", "")
            amount = 0
            try:
                amount = float(request.form.get("budget_amount", 0))
            except (TypeError, ValueError):
                pass
            month = request.form.get("month", selected_month)
            if not valid_month(month):
                month = selected_month
            valid_categories = (
                CATEGORY_GROUPS["fixed_expense"]
                + CATEGORY_GROUPS["variable_expense"]
            )
            if category in valid_categories and amount > 0:
                conn = get_db()
                conn.execute(
                    "INSERT INTO budgets (user_id, category, month, budget_amount) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id, category, month) "
                    "DO UPDATE SET budget_amount = excluded.budget_amount",
                    (current_user.id, category, month, amount),
                )
                conn.commit()
                conn.close()
                progress = get_budget_progress(current_user.id, month, threshold)
                item = next(
                    (row for row in progress if row["category"] == category), None
                )
                if item and settings["budget_alerts"] and item["percentage"] >= threshold:
                    flash(f"{category} has reached {item['percentage']}% of its budget.")
                else:
                    flash("Budget saved.")
            else:
                flash("Please choose a valid expense category and amount.")
            return redirect(url_for("budget", month=month))

        comparison = get_budget_progress(current_user.id, selected_month, threshold)
        return render_template(
            "budget.html",
            comparison=comparison,
            all_expense_categories=(
                CATEGORY_GROUPS["fixed_expense"]
                + CATEGORY_GROUPS["variable_expense"]
            ),
            already_budgeted=[row["category"] for row in comparison],
            this_month=selected_month,
            alert_threshold=threshold,
            total_budget=sum(row["budget"] for row in comparison),
            total_actual=sum(row["actual"] for row in comparison),
            total_difference=sum(row["difference"] for row in comparison),
        )

    @app.route("/budget/delete/<path:category>/<month>", methods=["POST"])
    @login_required
    def delete_budget(category, month):
        conn = get_db()
        conn.execute(
            "DELETE FROM budgets WHERE user_id = ? AND category = ? AND month = ?",
            (current_user.id, category, month),
        )
        conn.commit()
        conn.close()
        flash("Budget removed.")
        redirect_month = month if valid_month(month) else date.today().strftime("%Y-%m")
        return redirect(url_for("budget", month=redirect_month))
