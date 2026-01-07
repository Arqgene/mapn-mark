from flask import render_template, request, redirect, url_for, session, send_file
from models.db import get_db_connection, get_run_by_id
from datetime import datetime
import traceback
import os
import uuid
from threading import Thread
import subprocess
from models.pipeline import run_pipeline_async
from models.newpipeline import run_pipeline_async as run_specific_tool_pipeline
import shutil
import re

# -----------------------------
# ANSI STRIPPER (for clean logs)
# -----------------------------
# -----------------------------
# ANSI STRIPPER (for clean logs)
# -----------------------------
ANSI_ESCAPE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)

def terminate_pipeline(username: str, run_id: str) -> bool:
    """Helper to terminate a running pipeline (WSL process + flag file)."""
    run_dir = get_run_dir(username, run_id)
    if not os.path.exists(run_dir):
        return False

    # Write CANCEL flag
    cancel_file = os.path.join(run_dir, "CANCEL")
    with open(cancel_file, "w") as f:
        f.write("PIPELINE ABORTED BY USER\n")
 
    subprocess.run(
        ["wsl", "--terminate", "Ubuntu"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return True

# -----------------------------
# TOOL DEFINITIONS
# -----------------------------
ALL_TOOLS = {
    "porechop",
    "filtlong",
    "flye",
    "minimap2",
    "racon",
    "prokka",
    "quast",
    "fastqc"
}

PIPELINE_RUNS_DIR = "pipeline_runs"

# -----------------------------
# HELPERS
# -----------------------------
def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")

def get_run_dir(username: str, run_id: str) -> str:
    return os.path.join(
        PIPELINE_RUNS_DIR,
        safe_username(username),
        run_id
    )

def log_run_start(run_id, user_email):
    """Logs the start of a pipeline run to the database."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO pipeline_runs (run_id, user_email, status, start_time) VALUES (%s, %s, %s, %s)",
                (run_id, user_email, 'running', datetime.now())
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Failed to log run start: {e}")

def log_run_end(run_id, status):
    """Logs the end of a pipeline run to the database."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE pipeline_runs SET status = %s, end_time = %s WHERE run_id = %s",
                (status, datetime.now(), run_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
             print(f"Failed to log run end: {e}")

def run_pipeline_wrapper(run_id, user_email, mode, *args):
    """Wraps the pipeline execution to handle DB logging."""
    try:
        if mode == "single":
             # args format for single: input_fastq_path, output_dir, genome_size, threads, log_file, min_length, keep_percent, selected_tools
             run_specific_tool_pipeline(*args)
        else:
             # args format for full: input_fastq_path, output_dir, genome_size, threads, log_file, min_length, keep_percent
             run_pipeline_async(*args)
        
        # Determine final status
        # The args[1] is always output_dir in both calls above
        output_dir = args[1]
        
        if os.path.exists(os.path.join(output_dir, "CANCEL")) or os.path.exists(os.path.join(output_dir, "PIPELINE_ABORTED")):
            log_run_end(run_id, 'cancelled')
        elif os.path.exists(os.path.join(output_dir, "PIPELINE_DONE")):
            log_run_end(run_id, 'completed')
        else:
             # Fallback if no specific flag found but process finished (likely error or empty run)
             # Check for error in log?
             log_run_end(run_id, 'completed') # Assume completed if no error flag, or maybe 'failed'? 
             # Let's stick to 'completed' if it finished without abort, or maybe check for PIEPLINE_DONE explicitly.
             # If PIEPLINE_DONE is missing, it might have crashed.
             if not os.path.exists(os.path.join(output_dir, "PIPELINE_DONE")):
                 log_run_end(run_id, 'failed')

    except Exception as e:
        print(f"Pipeline wrapper error: {e}")
        traceback.print_exc()
        log_run_end(run_id, 'failed')

# -----------------------------
# INDEX / SUBMIT PIPELINE
# -----------------------------
def index():
    if request.method == "POST":
        if "user" not in session:
            return redirect(url_for("login"))

        username = session["user"]
        run_id = uuid.uuid4().hex[:8]
        session["run_id"] = run_id

        # User-scoped output directory
        output_dir = get_run_dir(username, run_id)
        os.makedirs(output_dir, exist_ok=True)

        # FASTQ upload
        input_fastq_file = request.files.get("input_fastq")
        if not input_fastq_file or input_fastq_file.filename == "":
            return render_template(
                "index.html",
                error="No FASTQ file selected."
            )

        input_fastq_path = os.path.join(output_dir, input_fastq_file.filename)
        input_fastq_file.save(input_fastq_path)

        # Parameters
        genome_size = request.form.get("genome_size")
        threads = request.form.get("threads")
        min_length = request.form.get("min_length")
        keep_percent = request.form.get("keep_percent")

        # Tool selection
        selected_tools = request.form.getlist("tools")

        if not selected_tools:
            return render_template(
                "index.html",
                error="Please select at least one tool."
            )

        # -----------------------------
        # VALIDATION: Check Dependencies
        # -----------------------------
        # Tools that require an assembly (Flye)
        post_assembly_tools = {"minimap2", "racon", "prokka", "quast"}
        
        # Check if any post-assembly tool is selected
        has_post_assembly = any(t in selected_tools for t in post_assembly_tools)
        
        # Check if assembler is missing
        if has_post_assembly and "flye" not in selected_tools:
             return render_template(
                "index.html",
                error="Invalid Selection: Prokka, Racon, Minimap2, and QUAST require 'Flye' (Assembler) to be selected."
            )


        # Mode enforcement
        if set(selected_tools) == ALL_TOOLS:
            mode = "full"
        else:
            mode = "single"

        # Log file
        log_file = os.path.join(output_dir, "pipeline_output.log")

        # Launch pipeline
        log_run_start(run_id, username)

        if mode == "full":
            Thread(
                target=run_pipeline_wrapper,
                args=(
                    run_id,
                    username,
                    "full",
                    input_fastq_path,
                    output_dir,
                    genome_size,
                    threads,
                    log_file,
                    min_length,
                    keep_percent
                ),
                daemon=True
            ).start()
        else:
            Thread(
                target=run_pipeline_wrapper,
                args=(
                    run_id,
                    username,
                    "single",
                    input_fastq_path,
                    output_dir,
                    genome_size,
                    threads,
                    log_file,
                    min_length,
                    keep_percent,
                    selected_tools
                ),
                daemon=True
            ).start()

        return redirect(url_for("status", run_id=run_id))

    return render_template("index.html")

# -----------------------------
# STATUS PAGE
# -----------------------------
def status(run_id):
    username = session.get("user")
    if not username:
        return redirect(url_for("login"))

    run_dir = get_run_dir(username, run_id)

    pipeline_log = os.path.join(run_dir, "pipeline_output.log")
    done_flag = os.path.join(run_dir, "PIPELINE_DONE")
    cancel_flag = os.path.join(run_dir, "CANCEL")

    output = ""
    if os.path.exists(pipeline_log):
        with open(pipeline_log, "r", encoding="utf-8", errors="replace") as f:
            output = strip_ansi(f.read())

    # 1. Get State from DB (Source of Truth)
    run_data = get_run_by_id(run_id)
    db_status = run_data['status'] if run_data else 'unknown'
    start_time = run_data['start_time'].timestamp() if run_data and run_data['start_time'] else None

    # 2. File-based Fallbacks (for backwards compatibility)
    file_is_aborted = (
        "PIPELINE ABORTED BY USER" in output
        or os.path.exists(cancel_flag)
    )

    file_is_complete = (
        "PIPELINE FINISHED SUCCESSFULLY" in output
        or "PIPELINE FINISHED" in output
        or os.path.exists(done_flag)
    )

    # 3. Determine Final State
    # DB takes precedence if it says completed/cancelled/failed
    # Otherwise check files
    
    is_cancelled = (db_status == 'cancelled') or file_is_aborted
    is_complete = (db_status == 'completed') or file_is_complete
    is_failed = (db_status == 'failed')
    
    # If DB says running, but file implies finished/cancelled, trust file and sync DB later (lazy)
    # For now, let's just make sure "failed" shows up as NOT running.
    
    is_running = (db_status == 'running') and not is_complete and not is_cancelled and not is_failed

    # -----------------------------
    # AUTO-TERMINATION ON ERROR
    # -----------------------------
    if is_running and output:
        # Check for error keywords - Refined to avoid false positives (e.g. "non-fatal ERRORs")
        error_keywords = ["Traceback", "Exception", "PIPELINE ABORTED", "Pipeline aborted", "Fatal Error"]
        
        # Check for "Error" only if it's not part of "non-fatal ERRORs" or similar safe contexts
        has_critical_error = any(keyword in output for keyword in error_keywords)
        
        # Strict check for generic 'Error'/'Failed' at start of line or specific contexts if needed
        # For now, relying on Traceback/Exception/Aborted is safer. 
        # Adding simple check for "Error:" or "Failed:" might be better than bare word.
        if "Error:" in output or "Failed:" in output:
            has_critical_error = True

        if has_critical_error:
             # Trigger termination
             terminate_pipeline(username, run_id)
             is_cancelled = True # Treat error as cancelled/stopped for UI mostly, or add specific failed state
             is_running = False
             # Append message to log if not present
             if "Auto-terminated due to error" not in output:
                 with open(pipeline_log, "a") as f:
                     f.write("\n\n[SYSTEM] Auto-terminated pipeline due to detected error in logs.\n")
             
             # Update DB to failed explicitly
             log_run_end(run_id, 'failed')
             is_failed = True

    return render_template(
        "status.html",
        run_id=run_id,
        output=output,
        is_running=is_running,
        is_complete=is_complete,
        is_cancelled=is_cancelled,
        is_failed=is_failed,
        start_time=start_time
    )

# -----------------------------
# LIVE LOG FETCH (AJAX)
# -----------------------------
def get_log(run_id):
    username = session.get("user")
    run_dir = get_run_dir(username, run_id)

    log_file = os.path.join(run_dir, "pipeline_output.log")
    cancel_flag = os.path.join(run_dir, "CANCEL")

    if os.path.exists(cancel_flag):
        return "PIPELINE ABORTED BY USER\nExecution stopped."

    if not os.path.exists(log_file):
        return "Waiting for pipeline to start..."

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return strip_ansi(f.read())

# -----------------------------
# DOWNLOAD RESULTS
# -----------------------------
import zipfile

def download_output(run_id):
    username = session.get("user")
    run_dir = get_run_dir(username, run_id)

    zip_base = os.path.dirname(run_dir)
    zip_filename = f"{run_id}.zip"
    zip_path = os.path.join(zip_base, zip_filename)

    # FAST ZIP: Use ZIP_STORED (no compression) for maximum speed
    # or ZIP_DEFLATED with low compresslevel if size matters slightly.
    # User asked for "faster", so ZIP_STORED is safest bet for speed.
    if not os.path.exists(zip_path):
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            for root, dirs, files in os.walk(run_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, run_dir)
                    zipf.write(file_path, arcname)

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"{run_id}_output.zip"
    )
# -----------------------------
# CANCEL RUN
# -----------------------------
def cancel_run(run_id):
    username = session.get("user")
    terminate_pipeline(username, run_id)
    return redirect(url_for("status", run_id=run_id))
