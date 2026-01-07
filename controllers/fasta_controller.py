from flask import render_template, request, flash, redirect, url_for, session, jsonify
from utils.blast_utils import run_blast_pipeline
from utils.mailer import send_run_completion_email, send_run_start_email
from models.db import get_db_connection
import threading
import uuid
import datetime
import os
import csv
import traceback

import traceback

def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")

def index():
    return render_template("fasta_compare.html")


def run_blast_async_worker(run_id, user_email, query_content, base_dir, output_file, query_filename, run_url):
    """
    Background worker to run BLAST pipeline.
    """
    connection = get_db_connection()
    try:
        # 1. Update status to RUNNING
        if connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE pipeline_runs SET status = 'running' WHERE run_id = %s", (run_id,))
            connection.commit()
            cursor.close()


        # 1.5 Send Start Email
        if user_email:
            send_run_start_email(user_email, run_id, tool_name="BLAST", run_url=run_url)

        # 2. Prepare files
        query_path = os.path.join(base_dir, "query.fasta")
        with open(query_path, "w", encoding="utf-8") as f:
            f.write(query_content)

        # 3. Run Pipeline
        # Note: default threads=4, max_hits=10. Could be parameterized.
        blast_db_path = os.path.join(os.getcwd(), "blast_db", "reference")
        
        run_blast_pipeline(
            query_fasta=query_path,
            output_dir=base_dir,
            blast_db_path=blast_db_path,
            threads=4,
            output_file=output_file
        )

        # 4. Update status to COMPLETED
        if connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE pipeline_runs SET status = 'completed', end_time = NOW() WHERE run_id = %s", (run_id,))
            connection.commit()
            cursor.close()

        # 5. Send Email
        if user_email:
            send_run_completion_email(user_email, run_id, "completed", run_url=run_url, tool_name="BLAST")

    except Exception as e:
        print(f"BLAST Worker Failed: {e}")
        traceback.print_exc()
        
        # Write error to log
        with open(output_file, "a") as f:
            f.write(f"\n[FATAL ERROR] {str(e)}\n")

        # Update status to FAILED
        if connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE pipeline_runs SET status = 'failed', end_time = NOW() WHERE run_id = %s", (run_id,))
            connection.commit()
            cursor.close()
            
        if user_email:
            send_run_completion_email(user_email, run_id, "failed", tool_name="BLAST")

    finally:
        if connection and connection.is_connected():
            connection.close()


def compare():
    if "file1" not in request.files:
        flash("Please upload a FASTA file.", "error")
        return redirect(url_for('index'))

    file1 = request.files["file1"]

    if not file1.filename:
        flash("No file selected.", "error")
        return redirect(url_for('index'))

    # Prepare Run ID
    run_id = "blast_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    user_email = session.get('user')  # 'user' stores the email, guaranteed by login_required
    
    # Create DB Entry
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        # Ensure run_type='blast'
        cursor.execute(
            "INSERT INTO pipeline_runs (run_id, user_email, status, start_time, run_type) VALUES (%s, %s, %s, NOW(), 'blast')",
            (run_id, user_email, 'pending')
        )
        connection.commit()
        cursor.close()
        connection.close()
    else:
        flash("Database connection error. Run cannot start.", "error")
        return redirect(url_for('index'))

    # Setup Directory
    # base_dir = os.path.join(os.getcwd(), "pipeline_runs", run_id) # OLD
    # NEW: pipeline_runs/username/run_id
    base_dir = os.path.join(os.getcwd(), "pipeline_runs", safe_username(user_email), run_id)
    os.makedirs(base_dir, exist_ok=True)
    output_file = os.path.join(base_dir, "blast.log")

    # Read Content (small files assumed, else stream)
    content = file1.read().decode("utf-8")

    # Generate external URL for email before threading (requires request context)
    run_url = url_for('blast_result', run_id=run_id, _external=True)

    # Start Background Thread
    thread = threading.Thread(
        target=run_blast_async_worker,
        args=(run_id, user_email, content, base_dir, output_file, file1.filename, run_url)
    )
    thread.daemon = True
    thread.start()

    # Redirect to Status Page
    return redirect(url_for('blast_status', run_id=run_id))


def blast_status(run_id):
    """
    Renders the status page for a BLAST run.
    """
    connection = get_db_connection()
    run = None
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM pipeline_runs WHERE run_id = %s", (run_id,))
        run = cursor.fetchone()
        cursor.close()
        connection.close()

    if not run:
        flash("Run not found.", "error")
        return redirect(url_for('index'))
        
    if run['status'] == 'completed':
        return redirect(url_for('blast_result', run_id=run_id))
    
    return render_template("blast_status.html", run=run)


def blast_result(run_id):
    """
    Renders the results for a completed BLAST run.
    """
    # 1. Verify Run & Get Path
    connection = get_db_connection()
    user_email = None
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_email FROM pipeline_runs WHERE run_id = %s", (run_id,))
        run_data = cursor.fetchone()
        if run_data:
            user_email = run_data['user_email']
        cursor.close()
        connection.close()

    if not user_email:
        # Fallback to session user if DB fails or legacy (less robust but keeps working for current user)
        user_email = session.get('user')

    base_dir = os.path.join(os.getcwd(), "pipeline_runs", safe_username(user_email), run_id)
    if not os.path.exists(base_dir):
         # Check legacy path
         legacy_dir = os.path.join(os.getcwd(), "pipeline_runs", run_id)
         if os.path.exists(legacy_dir):
             base_dir = legacy_dir

    result_file = os.path.join(base_dir, "blast_results.tsv")
    log_file = os.path.join(base_dir, "blast.log")
    
    if not os.path.exists(result_file):
        # Maybe it failed but marked completed? Or file missing?
        # Check logs
        log_content = "Log file not found."
        if os.path.exists(log_file):
             with open(log_file, 'r') as f: log_content = f.read()
             
        return render_template("blast_status.html", run={'run_id': run_id, 'status': 'failed'}, error_log=log_content)

    # 2. Parse Results
    results = []
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 12: continue
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
    except Exception as e:
        flash(f"Error parsing results: {e}", "error")

    return render_template("fasta_result.html", results=results, filename=f"Run {run_id}", run_id=run_id)


def blast_status_api(run_id):
    """
    API for polling status.
    """
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT status, user_email FROM pipeline_runs WHERE run_id = %s", (run_id,))
        run = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if run:
            # Fetch real-time logs
            log_content = ""
            # Get path using owner email
            base_dir = os.path.join(os.getcwd(), "pipeline_runs", safe_username(run['user_email'] if 'user_email' in run else session.get('user')), run_id)
            if not os.path.exists(base_dir):
                 legacy_dir = os.path.join(os.getcwd(), "pipeline_runs", run_id)
                 if os.path.exists(legacy_dir):
                     base_dir = legacy_dir
            
            log_file = os.path.join(base_dir, "blast.log")
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r") as f:
                        # Read last 2KB to avoid huge payloads
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(size - 2048, 0))
                        log_content = f.read()
                except:
                    pass

            return jsonify({"status": run['status'], "log": log_content})
    
    return jsonify({"status": "unknown"}), 404

def download_blast_csv(run_id):
    """
    Converts and downloads the BLAST results as CSV.
    """
    # 1. Verify availability
    connection = get_db_connection()
    user_email = None
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_email FROM pipeline_runs WHERE run_id = %s", (run_id,))
        run_data = cursor.fetchone()
        if run_data:
            user_email = run_data['user_email']
        cursor.close()
        connection.close()
    
    if not user_email:
        user_email = session.get('user')

    base_dir = os.path.join(os.getcwd(), "pipeline_runs", safe_username(user_email), run_id)
    if not os.path.exists(base_dir):
         legacy_dir = os.path.join(os.getcwd(), "pipeline_runs", run_id)
         if os.path.exists(legacy_dir):
             base_dir = legacy_dir

    result_file = os.path.join(base_dir, "blast_results.tsv")
    
    if not os.path.exists(result_file):
        flash("Results not found.", "error")
        return redirect(url_for('blast_result', run_id=run_id))
    
    # 2. Process and Stream
    import io
    from flask import Response
    
    # Generate CSV in memory or stream it
    def generate():
        # Header
        yield "Query ID,Subject ID,Identity (%),Alignment Length,Mismatches,Gap Opens,Q. Start,Q. End,S. Start,S. End,E-value,Bit Score\n"
        with open(result_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 12: continue
                # CSV escape if needed, simple join for now as data is numeric/id
                yield ",".join(f'"{x}"' for x in row) + "\n"
    
    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=blast_results_{run_id}.csv"}
    )
