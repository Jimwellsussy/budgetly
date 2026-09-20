import os

from flask import Flask, render_template
from flask_login import current_user, login_required, LoginManager
from flask_mail import Mail
from flask_wtf import CSRFProtect
from itsdangerous import URLSafeTimedSerializer

from auth.routes import register_routes as register_auth_routes
from budgets.routes import get_budget_progress, register_routes as register_budget_routes
from config import CURRENCY_SYMBOLS, configure_app
from database import get_user_settings, init_db, migrate_db
from goals.routes import register_routes as register_goal_routes
from reports.routes import get_report_data, register_routes as register_report_routes
from transactions.routes import (
    get_month_transactions,
    register_routes as register_transaction_routes,
    summarize,
)


app = Flask(__name__)
configure_app(app)
csrf = CSRFProtect(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
reset_serializer = URLSafeTimedSerializer(app.secret_key)


@app.context_processor
def inject_user_preferences():
    if not current_user.is_authenticated:
        return {"currency_symbol": CURRENCY_SYMBOLS["PHP"], "compact_mode": False}
    settings = get_user_settings(current_user.id)
    return {
        "currency_symbol": CURRENCY_SYMBOLS.get(settings["currency"], "₱"),
        "compact_mode": bool(settings["compact_mode"]),
    }


@app.route("/")
@login_required
def dashboard():
    from datetime import date

    this_month = date.today().strftime("%Y-%m")
    transactions = get_month_transactions(current_user.id, this_month)
    totals, category_totals = summarize(transactions)
    income = totals["income"]
    expenses = totals["fixed_expense"] + totals["variable_expense"]
    savings = totals["savings"]
    remaining = income - expenses - savings
    savings_rate = savings / income * 100 if income else 0
    expense_rate = expenses / income * 100 if income else 0
    remaining_rate = remaining / income * 100 if income else 0

    from database import get_db

    conn = get_db()
    recent = conn.execute(
        "SELECT * FROM transactions "
        "WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 6",
        (current_user.id,),
    ).fetchall()
    conn.close()

    report = get_report_data(current_user.id, 6)
    settings = get_user_settings(current_user.id)
    budget_progress = get_budget_progress(
        current_user.id,
        this_month,
        int(settings["budget_alert_threshold"]),
    )
    biggest_category = max(category_totals, key=category_totals.get) if category_totals else None
    return render_template(
        "dashboard.html",
        income=income,
        expenses=expenses,
        savings=savings,
        remaining=remaining,
        savings_rate=savings_rate,
        expense_rate=expense_rate,
        remaining_rate=remaining_rate,
        category_totals=category_totals,
        recent=recent,
        biggest_category=biggest_category,
        this_month=this_month,
        budget_progress=budget_progress,
        trend_labels=report["trend_labels"],
        trend_income=report["trend_income"],
        trend_expense=report["trend_expense"],
        trend_net=report["trend_net"],
    )


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        code=404,
        message="The page you requested could not be found.",
    ), 404


@app.errorhandler(413)
def too_large(error):
    return render_template(
        "error.html",
        code=413,
        message="That upload is too large. The limit is 2 MB.",
    ), 413


@app.errorhandler(500)
def server_error(error):
    return render_template(
        "error.html",
        code=500,
        message="Something went wrong. Please try again.",
    ), 500


register_auth_routes(app, login_manager, mail, reset_serializer)
register_transaction_routes(app)
register_budget_routes(app)
register_goal_routes(app)
register_report_routes(app)

init_db()
migrate_db()


if __name__ == "__main__":
    debug = os.environ.get("BUDGETLY_DEBUG", "0").lower() in ("1", "true", "yes")
    app.run(debug=debug)
