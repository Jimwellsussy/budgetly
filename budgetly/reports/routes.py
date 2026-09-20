import csv
import io
from datetime import date

from flask import Response, render_template, request
from flask_login import current_user, login_required

from database import get_db


def month_sequence(count):
    today = date.today()
    result = []
    year, month = today.year, today.month
    for _ in range(count):
        result.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(result))


def get_report_data(user_id, months=6):
    month_labels = month_sequence(months)
    start_month = month_labels[0]
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND date >= ? "
        "ORDER BY date ASC, id ASC",
        (user_id, f"{start_month}-01"),
    ).fetchall()
    conn.close()

    monthly = {
        month: {"income": 0, "expense": 0, "savings": 0, "net": 0}
        for month in month_labels
    }
    top_categories = {}
    current_month = date.today().strftime("%Y-%m")
    current_category_totals = {}
    for transaction in rows:
        month = transaction["date"][:7]
        if month not in monthly:
            continue
        amount = transaction["amount"]
        group = transaction["group_name"]
        if group == "income":
            monthly[month]["income"] += amount
        elif group in ("fixed_expense", "variable_expense"):
            monthly[month]["expense"] += amount
            top_categories[transaction["category"]] = (
                top_categories.get(transaction["category"], 0) + amount
            )
            if month == current_month:
                current_category_totals[transaction["category"]] = (
                    current_category_totals.get(transaction["category"], 0) + amount
                )
        elif group == "savings":
            monthly[month]["savings"] += amount

    for values in monthly.values():
        values["net"] = values["income"] - values["expense"] - values["savings"]
    monthly_rows = [{"month": month, **monthly[month]} for month in month_labels]
    total_income = sum(row["income"] for row in monthly_rows)
    total_expenses = sum(row["expense"] for row in monthly_rows)
    total_savings = sum(row["savings"] for row in monthly_rows)
    return {
        "trend_labels": month_labels,
        "trend_income": [row["income"] for row in monthly_rows],
        "trend_expense": [row["expense"] for row in monthly_rows],
        "trend_savings": [row["savings"] for row in monthly_rows],
        "trend_net": [row["net"] for row in monthly_rows],
        "monthly_rows": monthly_rows,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "total_savings": total_savings,
        "total_net": total_income - total_expenses - total_savings,
        "top_categories": sorted(
            top_categories.items(), key=lambda item: item[1], reverse=True
        ),
        "current_category_totals": current_category_totals,
    }


def register_routes(app):
    @app.route("/reports")
    @login_required
    def reports():
        try:
            months = int(request.args.get("months", 6))
        except ValueError:
            months = 6
        months = months if months in (3, 6, 12) else 6
        report = get_report_data(current_user.id, months)
        return render_template(
            "reports.html",
            months=months,
            trend_labels=report["trend_labels"],
            trend_income=report["trend_income"],
            trend_expense=report["trend_expense"],
            trend_savings=report["trend_savings"],
            trend_net=report["trend_net"],
            monthly_rows=report["monthly_rows"],
            total_income=report["total_income"],
            total_expenses=report["total_expenses"],
            total_savings=report["total_savings"],
            total_net=report["total_net"],
            top_categories=report["top_categories"],
            category_totals=report["current_category_totals"],
        )

    @app.route("/reports/export.csv")
    @login_required
    def export_reports_csv():
        try:
            months = int(request.args.get("months", 6))
        except ValueError:
            months = 6
        months = months if months in (3, 6, 12) else 6
        report = get_report_data(current_user.id, months)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Month", "Income", "Expenses", "Savings", "Net"])
        for row in report["monthly_rows"]:
            writer.writerow([
                row["month"], row["income"], row["expense"],
                row["savings"], row["net"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=budgetly-report-{months}m.csv"
                )
            },
        )
