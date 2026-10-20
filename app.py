
from flask import Flask, render_template, request, session, redirect, url_for
from database import get_connection, initialize_database
from datetime import datetime
from uuid import uuid4

app = Flask(__name__)
app.secret_key = "local-training-demo-key"

emails = [
    {
        "id": 1,
        "sender": "security@example.invalid",
        "subject": "Urgent: Verify Your Account",
        "message": "Your account needs attention. Review this training message.",
        "answer": "phishing",
        "reason": "Urgent requests to verify an account can be a warning sign."
    },
    {
        "id": 2,
        "sender": "library@example.edu",
        "subject": "Library Schedule Update",
        "message": "The library will open at 9 AM next Monday.",
        "answer": "legitimate",
        "reason": "This is a routine announcement in our fictional training scenario."
    },
    {
        "id": 3,
        "sender": "rewards@example.invalid",
        "subject": "Unexpected Prize",
        "message": "This mock message asks you to claim an unexpected reward.",
        "answer": "phishing",
        "reason": "Unexpected prizes and pressure to act can be warning signs."
    }
]


def create_training_session():
    token = str(uuid4())
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO training_sessions (session_token, total_scenarios)
        VALUES (?, ?)
        """,
        (token, len(emails))
    )

    connection.commit()
    training_id = cursor.lastrowid
    connection.close()

    session["training_id"] = training_id
    session["answered"] = []
    session["score"] = 0
    session["incorrect"] = []

    return training_id


def ensure_training_session():
    initialize_database()

    if "training_id" not in session:
        return create_training_session()

    return session["training_id"]


@app.route("/")
def home():
    ensure_training_session()

    answered = session.get("answered", [])
    score = session.get("score", 0)
    incorrect = session.get("incorrect", [])

    return render_template(
        "index.html",
        emails=emails,
        score=score,
        answered=answered,
        incorrect=incorrect
    )


@app.route("/answer/<int:email_id>", methods=["POST"])
def answer(email_id):
    training_id = ensure_training_session()

    item = next(
        (email for email in emails if email["id"] == email_id),
        None
    )

    if item is None:
        return "Scenario not found", 404

    choice = request.form.get("choice", "")

    if choice not in ("phishing", "legitimate"):
        return "Invalid choice", 400

    answered = session.get("answered", [])
    score = session.get("score", 0)
    incorrect = session.get("incorrect", [])

    correct = choice == item["answer"]

    # Save only the first answer for each scenario.
    if email_id not in answered:
        answered.append(email_id)

        if correct:
            score += 1
        else:
            incorrect.append(email_id)

        connection = get_connection()

        connection.execute(
            """
            INSERT OR IGNORE INTO responses
            (session_id, scenario_id, selected_answer, correct)
            VALUES (?, ?, ?, ?)
            """,
            (
                training_id,
                email_id,
                choice,
                int(correct)
            )
        )

        is_complete = len(answered) == len(emails)

        connection.execute(
            """
            UPDATE training_sessions
            SET correct_answers = ?,
                incorrect_answers = ?,
                completed = ?,
                completed_at = CASE
                    WHEN ? = 1 THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE id = ?
            """,
            (
                score,
                len(incorrect),
                int(is_complete),
                int(is_complete),
                training_id
            )
        )

        connection.commit()
        connection.close()

        session["answered"] = answered
        session["score"] = score
        session["incorrect"] = incorrect
        session.modified = True

    return render_template(
        "result.html",
        email=item,
        choice=choice,
        correct=correct,
        score=score,
        total=len(emails)
    )


@app.route("/reset")
def reset():
    # Keep historical database records; start a fresh training session.
    session.clear()
    return redirect(url_for("home"))


@app.route("/results")
def results():
    initialize_database()
    connection = get_connection()

    training_sessions = connection.execute(
        """
        SELECT id, started_at, completed_at, total_scenarios,
               correct_answers, incorrect_answers, completed
        FROM training_sessions
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "results.html",
        training_sessions=training_sessions
    )


@app.route("/analysis")
def analysis():
    initialize_database()
    connection = get_connection()

    summary = connection.execute(
        """
        SELECT
            COUNT(*) AS total_sessions,
            SUM(completed) AS completed_sessions,
            AVG(
                CASE WHEN completed = 1
                THEN 100.0 * correct_answers / total_scenarios
                END
            ) AS average_accuracy
        FROM training_sessions
        """
    ).fetchone()

    mistakes = connection.execute(
        """
        SELECT scenario_id, COUNT(*) AS mistake_count
        FROM responses
        WHERE correct = 0
        GROUP BY scenario_id
        ORDER BY mistake_count DESC
        """
    ).fetchall()

    connection.close()

    subjects = {
        email["id"]: email["subject"]
        for email in emails
    }

    mistake_summary = [
        {
            "subject": subjects.get(row["scenario_id"], "Unknown scenario"),
            "mistake_count": row["mistake_count"]
        }
        for row in mistakes
    ]

    return render_template(
        "analysis.html",
        summary=summary,
        mistake_summary=mistake_summary
    )


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
