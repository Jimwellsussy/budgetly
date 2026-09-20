from datetime import date, datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import get_db


def parse_amount(value):
    try:
        amount = float(value)
        return amount if amount > 0 else 0
    except (TypeError, ValueError):
        return 0


def register_routes(app):
    @app.route("/goals")
    @login_required
    def goals():
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY id DESC",
            (current_user.id,),
        ).fetchall()
        conn.close()

        today = date.today()
        prepared = []
        total_saved = total_target = 0
        completed_count = 0
        for row in rows:
            goal = dict(row)
            target = float(goal["target"])
            saved = min(max(float(goal["saved"]), 0), target)
            progress = min(100, saved / target * 100 if target else 0)
            remaining = max(0, target - saved)
            days_left = None
            if goal.get("target_date"):
                try:
                    days_left = (
                        datetime.strptime(goal["target_date"], "%Y-%m-%d").date()
                        - today
                    ).days
                except ValueError:
                    days_left = None

            if progress >= 100:
                status = "completed"
                completed_count += 1
            elif days_left is not None and days_left < 0:
                status = "overdue"
            elif days_left is not None and days_left <= 30:
                status = "due-soon"
            else:
                status = "in-progress"

            monthly_needed = 0
            if remaining and days_left is not None and days_left > 0:
                monthly_needed = remaining / max(1, days_left / 30)
            goal.update(
                saved=saved,
                progress=progress,
                remaining=remaining,
                days_left=days_left,
                status=status,
                monthly_needed=monthly_needed,
            )
            prepared.append(goal)
            total_saved += saved
            total_target += target

        return render_template(
            "goals.html",
            goals=prepared,
            total_saved=total_saved,
            total_target=total_target,
            overall_progress=total_saved / total_target * 100 if total_target else 0,
            completed_count=completed_count,
            today=today.isoformat(),
        )

    @app.route("/goals/add", methods=["POST"])
    @login_required
    def add_goal():
        name = request.form.get("name", "").strip()[:80]
        target = parse_amount(request.form.get("target"))
        target_date = request.form.get("target_date", "").strip() or None
        monthly_contribution = parse_amount(request.form.get("monthly_contribution"))
        if target_date:
            try:
                if datetime.strptime(target_date, "%Y-%m-%d").date() < date.today():
                    flash("Target date cannot be in the past.")
                    return redirect(url_for("goals"))
            except ValueError:
                flash("Please enter a valid target date.")
                return redirect(url_for("goals"))
        if not name or not target:
            flash("Please enter a goal name and target amount.")
            return redirect(url_for("goals"))
        conn = get_db()
        conn.execute(
            "INSERT INTO goals "
            "(user_id, name, target, saved, target_date, monthly_contribution) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (current_user.id, name, target, target_date, monthly_contribution),
        )
        conn.commit()
        conn.close()
        flash("Goal created.")
        return redirect(url_for("goals"))

    @app.route("/goals/update/<int:goal_id>", methods=["POST"])
    @login_required
    def update_goal(goal_id):
        try:
            saved = max(0, float(request.form.get("saved")))
        except (TypeError, ValueError):
            saved = 0
        conn = get_db()
        goal = conn.execute(
            "SELECT target FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, current_user.id),
        ).fetchone()
        if goal:
            saved = min(saved, goal["target"])
            conn.execute(
                "UPDATE goals SET saved = ? WHERE id = ? AND user_id = ?",
                (saved, goal_id, current_user.id),
            )
            conn.commit()
            flash("Goal progress updated.")
        conn.close()
        return redirect(url_for("goals"))

    @app.route("/goals/delete/<int:goal_id>", methods=["POST"])
    @login_required
    def delete_goal(goal_id):
        conn = get_db()
        conn.execute(
            "DELETE FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, current_user.id),
        )
        conn.commit()
        conn.close()
        flash("Goal deleted.")
        return redirect(url_for("goals"))
