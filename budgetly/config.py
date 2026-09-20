import os
import re


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "budgetly.db")

SECRET_KEY = os.environ.get("BUDGETLY_SECRET_KEY", "dev-secret-key-change-this-later")
MAX_CONTENT_LENGTH = 2 * 1024 * 1024

CATEGORY_GROUPS = {
    "income": ["Salary", "Freelance/Side Hustle", "Allowance", "Other Income"],
    "fixed_expense": ["Rent", "Internet", "Phone", "Insurance", "Subscriptions", "Loans/Debt"],
    "variable_expense": [
        "Food", "Transportation", "Groceries", "Entertainment",
        "Shopping", "Hobbies", "Miscellaneous",
    ],
    "savings": ["Emergency Fund", "General Savings", "Big Purchases", "Investments", "Vacation/Travel"],
}

GROUP_LABELS = {
    "income": "Income",
    "fixed_expense": "Fixed Expense",
    "variable_expense": "Variable Expense",
    "savings": "Savings",
}

PAYMENT_METHODS = ["Cash", "Debit Card", "Credit Card", "Bank Transfer", "GCash/E-wallet"]
INCOME_PAYMENT_METHODS = [
    "Cash received",
    "Bank transfer received",
    "Digital wallet received",
    "Other income",
]

CURRENCY_SYMBOLS = {
    "PHP": "₱",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "AUD": "A$",
}

SETTINGS_DEFAULTS = {
    "currency": "PHP",
    "week_start": "monday",
    "default_group": "variable_expense",
    "default_category": "Food",
    "default_payment_method": "Cash",
    "budget_alert_threshold": 80,
    "compact_mode": 0,
    "budget_alerts": 1,
    "weekly_summary": 0,
    "goal_reminders": 0,
}

SPECIAL_CHARS = ".!@#$%^&*"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def configure_app(app):
    app.secret_key = SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("BUDGETLY_COOKIE_SECURE", "0") == "1",
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", 587)),
        MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.environ.get("MAIL_USERNAME"),
    )
