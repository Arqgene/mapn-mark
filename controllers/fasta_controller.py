from flask import (
    render_template, request, flash, redirect,
    url_for, session, jsonify, Response
)
from utils.blast_utils import run_blast_pipeline
from utils.mailer import send_run_completion_email, send_run_start_email
from models.db import get_db_connection

import threading
import uuid
import datetime
import os
import csv
import traceback
import io


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")


# -------------------------------------------------
# UI
# -------------------------------------------------
def index():
    return render_template("fasta_compare.html")


# -------------------------------------------------
# Background Worker
# -------------------------------------------------
def run_blast_async_worker(
    run_id,
    user_email,
    query_content,
    base_dir,
    output_file,
    query_filename,
    run_url
):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE pipeline_runs SET status='running' WHERE run_id=%s",
                (run_id,)
            )
            connection.commit()
            cursor.close()
            cursor = None

        try:
            if user_email:
                send_run_start_email(
                    user_email, run_id,
                    tool_name="BLAST",
                    run_url=run_url
                )
        except Exception:
            pass  # Email failure must not kill pipeline

        query_path = os.path.join(base_dir, "query.fasta")
        with open(query_path, "w", encoding="utf-8") as f:
            f.write(query_content)

        blast_db_path = os.path.abspath(
            os.path.join(os.getcwd(), "blast_db", "reference")
        )

        run_blast_pipeline(
            query_fasta=query_path,
            output_dir=base_dir,
            blast_db_path=blast_db_path,
            threads=4,
            output_file=output_file
        )

        if connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE pipeline_runs SET status='completed', end_time=NOW() WHERE run_id=%s",
                (run_id,)
            )
            connection.commit()

        try:
            if user_email:
                send_run_completion_email(
                    user_email, run_id,
                    "completed",
                    run_url=run_url,
                    tool_name="BLAST"
                )
        except Exception:
            pass

    except Exception as e:
        traceback.print_exc()

        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"\n[FATAL ERROR] {str(e)}\n")

        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "UPDATE pipeline_runs SET status='failed', end_time=NOW() WHERE run_id=%s",
                    (run_id,)
                )
                connection.commit()
            except Exception:
                pass

        try:
            if user_email:
                send_run_completion_email(
                    user_email, run_id,
                    "failed",
                    tool_name="BLAST"
                )
        except Exception:
            pass

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# -------------------------------------------------
# Upload & Launch
# -------------------------------------------------
def compare():
    if "file1" not in request.files:
        flash("Please upload a FASTA file.", "error")
        return redirect(url_for("index"))

    file1 = request.files["file1"]
    if not file1.filename:
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    run_id = f"blast_{datetime.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    user_email = session.get("user")

    connection = get_db_connection()
    if not connection:
        flash("Database error.", "error")
        return redirect(url_for("index"))

    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO pipeline_runs
        (run_id, user_email, status, start_time, run_type)
        VALUES (%s, %s, 'pending', NOW(), 'blast')
        """,
        (run_id, user_email)
    )
    connection.commit()
    cursor.close()
    connection.close()

    base_dir = os.path.join(
        os.getcwd(), "pipeline_runs",
        safe_username(user_email), run_id
    )
    os.makedirs(base_dir, exist_ok=True)

    output_file = os.path.join(base_dir, "blast.log")
    content = file1.read().decode("utf-8")
    run_url = url_for("blast_result", run_id=run_id, _external=True)

    thread = threading.Thread(
        target=run_blast_async_worker,
        args=(
            run_id, user_email, content,
            base_dir, output_file,
            file1.filename, run_url
        ),
        daemon=True
    )
    thread.start()

    return redirect(url_for("blast_status", run_id=run_id))


# -------------------------------------------------
# Status Page
# -------------------------------------------------
def blast_status(run_id):
    connection = get_db_connection()
    run = None

    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM pipeline_runs WHERE run_id=%s",
            (run_id,)
        )
        run = cursor.fetchone()
        cursor.close()
        connection.close()

    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("index"))

    if run["status"] == "completed":
        return redirect(url_for("blast_result", run_id=run_id))

    return render_template("blast_status.html", run=run)


# -------------------------------------------------
# Results Page
# -------------------------------------------------
def blast_result(run_id):
    connection = get_db_connection()
    user_email = None

    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_email FROM pipeline_runs WHERE run_id=%s",
            (run_id,)
        )
        data = cursor.fetchone()
        cursor.close()
        connection.close()

        if data:
            user_email = data["user_email"]

    user_email = user_email or session.get("user")

    base_dir = os.path.join(
        os.getcwd(), "pipeline_runs",
        safe_username(user_email), run_id
    )

    result_file = os.path.join(base_dir, "blast_results.tsv")
    log_file = os.path.join(base_dir, "blast.log")

    if not os.path.exists(result_file):
        log_content = ""
        if os.path.exists(log_file):
            with open(log_file) as f:
                log_content = f.read()
        return render_template(
            "blast_status.html",
            run={"run_id": run_id, "status": "failed"},
            error_log=log_content
        )

    results = []
    with open(result_file, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 12:
                continue
            results.append({
                "query_id": row[0],
                "subject_id": row[1],
                "identity": float(row[2]),
                "align_len": int(row[3]),
                "mismatch": int(row[4]),
                "gaps": int(row[5]),
                "q_start": int(row[6]),
                "q_end": int(row[7]),
                "s_start": int(row[8]),
                "s_end": int(row[9]),
                "evalue": float(row[10]),
                "bitscore": float(row[11]),
            })

    return render_template(
        "fasta_result.html",
        results=results,
        filename=f"Run {run_id}",
        run_id=run_id
    )


# -------------------------------------------------
# Status API
# -------------------------------------------------
def blast_status_api(run_id):
    connection = get_db_connection()
    if not connection:
        return jsonify({"status": "unknown"}), 404

    cursor = connection.cursor(dictionary=True)
    cursor.execute(
        "SELECT status, user_email FROM pipeline_runs WHERE run_id=%s",
        (run_id,)
    )
    run = cursor.fetchone()
    cursor.close()
    connection.close()

    if not run:
        return jsonify({"status": "unknown"}), 404

    base_dir = os.path.join(
        os.getcwd(), "pipeline_runs",
        safe_username(run["user_email"]), run_id
    )

    log_content = ""
    log_file = os.path.join(base_dir, "blast.log")
    if os.path.exists(log_file):
        with open(log_file) as f:
            f.seek(max(0, os.path.getsize(log_file) - 2048))
            log_content = f.read()

    return jsonify({"status": run["status"], "log": log_content})


# -------------------------------------------------
# CSV Download
# -------------------------------------------------
def download_blast_csv(run_id):
    connection = get_db_connection()
    user_email = None

    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_email FROM pipeline_runs WHERE run_id=%s",
            (run_id,)
        )
        data = cursor.fetchone()
        cursor.close()
        connection.close()

        if data:
            user_email = data["user_email"]

    user_email = user_email or session.get("user")

    base_dir = os.path.join(
        os.getcwd(), "pipeline_runs",
        safe_username(user_email), run_id
    )

    result_file = os.path.join(base_dir, "blast_results.tsv")
    if not os.path.exists(result_file):
        flash("Results not found.", "error")
        return redirect(url_for("blast_result", run_id=run_id))

    def generate():
        yield (
            "Query ID,Subject ID,Identity (%),Alignment Length,"
            "Mismatches,Gap Opens,Q Start,Q End,"
            "S Start,S End,E-value,Bit Score\n"
        )
        with open(result_file, encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) >= 12:
                    yield ",".join(f'"{x}"' for x in row) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename=blast_results_{run_id}.csv"
        }
    )
