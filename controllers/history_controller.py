from flask import Blueprint, session, jsonify
from models.db import get_db_connection
from datetime import datetime
from utils.runtime import calculate_runtime

history_bp = Blueprint("history", __name__)

@history_bp.route("/api/history/running", methods=["GET"])
def get_running_instances():

    # -----------------------
    # Authentication
    # -----------------------
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_email = session["user_email"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT
            run_id,
            status,
            start_time
        FROM pipeline_runs
        WHERE user_email = %s
          AND status = 'running'
        ORDER BY start_time DESC
    """

    cursor.execute(query, (user_email,))
    rows = cursor.fetchall()

    result = []
    for row in rows:
        result.append({
            "run_id": row["run_id"],
            "status": row["status"],
            "start_time": row["start_time"].isoformat(),
            "runtime": calculate_runtime(row["start_time"])
        })

    cursor.close()
    conn.close()

    return jsonify(result), 200
