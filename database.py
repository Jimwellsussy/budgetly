import sqlite3
from datetime import datetime

from config import DB_PATH, SETTINGS_DEFAULTS


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_user_settings_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            currency TEXT NOT NULL DEFAULT 'PHP',
            week_start TEXT NOT NULL DEFAULT 'monday',
            default_group TEXT NOT NULL DEFAULT 'variable_expense',
            default_category TEXT NOT NULL DEFAULT 'Food',
            default_payment_method TEXT NOT NULL DEFAULT 'Cash',
            budget_alert_threshold INTEGER NOT NULL DEFAULT 80,
            compact_mode INTEGER NOT NULL DEFAULT 0,
            budget_alerts INTEGER NOT NULL DEFAULT 1,
            weekly_summary INTEGER NOT NULL DEFAULT 0,
            goal_reminders INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(user_settings)")}
    additions = {
        "currency": "TEXT NOT NULL DEFAULT 'PHP'",
        "week_start": "TEXT NOT NULL DEFAULT 'monday'",
        "default_group": "TEXT NOT NULL DEFAULT 'variable_expense'",
        "default_category": "TEXT NOT NULL DEFAULT 'Food'",
        "default_payment_method": "TEXT NOT NULL DEFAULT 'Cash'",
        "budget_alert_threshold": "INTEGER NOT NULL DEFAULT 80",
        "compact_mode": "INTEGER NOT NULL DEFAULT 0",
        "budget_alerts": "INTEGER NOT NULL DEFAULT 1",
        "weekly_summary": "INTEGER NOT NULL DEFAULT 0",
        "goal_reminders": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE user_settings ADD COLUMN {name} {definition}")


def ensure_recurring_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recurring_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            payment_method TEXT,
            day_of_month INTEGER NOT NULL DEFAULT 1,
            last_processed_month TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            payment_method TEXT,
            date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target REAL NOT NULL,
            saved REAL NOT NULL DEFAULT 0,
            target_date TEXT,
            monthly_contribution REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            month TEXT NOT NULL,
            budget_amount REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, category, month)
        )
    """)
    ensure_user_settings_table(conn)
    ensure_recurring_table(conn)
    conn.commit()
    conn.close()


def migrate_db():
    conn = get_db()
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "email" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")

    goal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(goals)")}
    if "target_date" not in goal_columns:
        conn.execute("ALTER TABLE goals ADD COLUMN target_date TEXT")
    if "monthly_contribution" not in goal_columns:
        conn.execute("ALTER TABLE goals ADD COLUMN monthly_contribution REAL NOT NULL DEFAULT 0")

    ensure_user_settings_table(conn)
    ensure_recurring_table(conn)
    for user in conn.execute("SELECT id FROM users").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id, updated_at) VALUES (?, ?)",
            (user["id"], datetime.utcnow().isoformat()),
        )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_group ON transactions(user_id, group_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_budgets_user_month ON budgets(user_id, month)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recurring_user_active ON recurring_transactions(user_id, active)")
    conn.commit()
    conn.close()


def get_user_settings(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id, updated_at) VALUES (?, ?)",
            (user_id, datetime.utcnow().isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    settings = dict(SETTINGS_DEFAULTS)
    if row:
        settings.update(dict(row))
    return settings


def save_user_settings(user_id, values):
    settings = dict(SETTINGS_DEFAULTS)
    settings.update(get_user_settings(user_id))
    settings.update(values)
    conn = get_db()
    conn.execute("""
        INSERT INTO user_settings (
            user_id, currency, week_start, default_group, default_category,
            default_payment_method, budget_alert_threshold, compact_mode,
            budget_alerts, weekly_summary, goal_reminders, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            currency = excluded.currency,
            week_start = excluded.week_start,
            default_group = excluded.default_group,
            default_category = excluded.default_category,
            default_payment_method = excluded.default_payment_method,
            budget_alert_threshold = excluded.budget_alert_threshold,
            compact_mode = excluded.compact_mode,
            budget_alerts = excluded.budget_alerts,
            weekly_summary = excluded.weekly_summary,
            goal_reminders = excluded.goal_reminders,
            updated_at = excluded.updated_at
    """, (
        user_id, settings["currency"], settings["week_start"],
        settings["default_group"], settings["default_category"],
        settings["default_payment_method"], settings["budget_alert_threshold"],
        int(bool(settings["compact_mode"])), int(bool(settings["budget_alerts"])),
        int(bool(settings["weekly_summary"])), int(bool(settings["goal_reminders"])),
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    conn.close()
