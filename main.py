from flask import (
    Flask, redirect, url_for, send_file,
    abort, request, render_template,
    flash, session, jsonify, after_this_request
)
from controllers import main_controller, diagnostics_controller, fasta_controller
from models.db import get_user_by_email, init_db, update_user_session_token, get_db_connection
from ai.chat_engine import build_prompt
from openai import OpenAI
from datetime import datetime

import subprocess
import os
import zipfile
import shutil
import tempfile
import uuid
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_key_fallback_do_not_use_in_prod")

# Increase max upload size to 16GB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024

PIPELINE_RUNS_DIR = "pipeline_runs"

def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")


def get_run_dir(email: str, run_id: str) -> Path:
    user_path = Path(PIPELINE_RUNS_DIR) / safe_username(email) / run_id
    if user_path.exists():
        return user_path

    flat_path = Path(PIPELINE_RUNS_DIR) / run_id
    if flat_path.exists():
        return flat_path

    return user_path


# =============================
# LOGIN REQUIRED DECORATOR
from datetime import timedelta, datetime

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_PERMANENT'] = False # Ensure cookie is deleted on browser close

@app.before_request
def make_session_permanent():
    session.permanent = False # Redundant but safe: verify strictly session-only cookie
    app.permanent_session_lifetime = timedelta(minutes=30) # For idle calculation logic if used elsewhere

@app.before_request
def check_session_validity():
    if "user" in session:
        # 1. Idle Check
        now = datetime.now().timestamp()
        last_active = session.get("last_active")
        
        if last_active and (now - last_active > 1800):
            session.clear()
            flash("Session expired due to inactivity. Please login again.", "info")
            return redirect(url_for("login"))
        
        session["last_active"] = now

        # 2. Concurrent Session Check (Single Session Enforcement)
        # Skip check for static assets to reduce DB load
        if request.endpoint and "static" not in request.endpoint:
            user = get_user_by_email(session["user"])
            if user and user.get("session_token") != session.get("token"):
                session.clear()
                flash("You have been logged out because your account was accessed from another device.", "warning")
                return redirect(url_for("login"))

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
             flash("Please provide both email and password.", "error")
        else:
            user = get_user_by_email(email)
            
            # Note: For production, use password hashing (e.g., bcrypt)!
            if user and user["password"] == password:
                # Generate new session token
                new_token = uuid.uuid4().hex
                update_user_session_token(email, new_token)
                
                session["user"] = user["email"]
                session["name"] = user["name"]
                session["role"] = user["role"]
                session["token"] = new_token
                session["last_active"] = datetime.now().timestamp()
                
                flash("Login successful.", "success")
                return redirect(url_for("index"))

            flash("Invalid credentials.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/create-user")
@login_required
def create_user():
    if session.get("role") != "admin":
        abort(403)
    return render_template("create_user.html")


@app.route("/api/create-user", methods=["POST"])
@login_required
def api_create_user():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    email = data.get("email")
    password = data.get("password")
    name = data.get("name")
    role = data.get("role", "user")

    if not all([email, password, name]):
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Check if user exists
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                return jsonify({"error": "User with this email already exists"}), 409

            # Insert new user
            cursor.execute(
                "INSERT INTO users (email, password, name, role) VALUES (%s, %s, %s, %s)",
                (email, password, name, role)
            )
            conn.commit()
            return jsonify({"message": "User created successfully"}), 201

        except Exception as e:
            print(f"Error creating user: {e}")
            return jsonify({"error": "Internal database error"}), 500
        finally:
            cursor.close()
            conn.close()
    
    return jsonify({"error": "Database connection failed"}), 500

# def create_run_zip(email: str, run_id: str):
#     run_dir = get_run_dir(email, run_id)

#     if not run_dir.exists():
#         abort(404, "Run not found")

#     tmp_dir = Path(tempfile.mkdtemp(prefix="mapnmark_zip_"))
#     zip_path = tmp_dir / f"{run_id}.zip"

#     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
#         for file in run_dir.rglob("*"):
#             if file.is_file():
#                 zipf.write(file, file.relative_to(run_dir))

#     return zip_path, tmp_dir

def get_or_create_run_zip(email: str, run_id: str) -> Path:
    run_dir = get_run_dir(email, run_id)
    if not run_dir.exists():
        abort(404, "Run not found")

    zip_path = run_dir / f"{run_id}.zip"

    # 1. Check if valid ZIP already exists
    if zip_path.exists():
        if zipfile.is_zipfile(zip_path):
            return zip_path
        else:
            print(f"Corrupt zip found at {zip_path}, regenerating...")
            try:
                os.remove(zip_path)
            except OSError:
                pass

    # 2. Atomic Creation (Write to temp, then rename)
    tmp_zip_path = run_dir / f"{run_id}.zip.tmp"
    
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in run_dir.rglob("*"):
                # Skip the zip file itself and any temp files
                if file.is_file() and file.name != zip_path.name and not file.name.endswith('.tmp'):
                    zipf.write(file, file.relative_to(run_dir))
        
        # Atomic move
        if tmp_zip_path.exists():
            tmp_zip_path.replace(zip_path)
            
    except Exception as e:
        print(f"Error creating zip: {e}")
        if tmp_zip_path.exists():
            try:
                os.remove(tmp_zip_path)
            except OSError:
                pass
        raise e

    return zip_path

def build_file_tree(paths):
    tree = {}
    for path in paths:
        parts = path.split(os.sep)
        cur = tree
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur.setdefault("__files__", []).append(parts[-1])
    return tree

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    return main_controller.index()


@app.route("/status/<run_id>")
@login_required
def status(run_id):
    return main_controller.status(run_id)


@app.route("/get_log/<run_id>")
@login_required
def get_log(run_id):
    return main_controller.get_log(run_id)

@app.route("/diagnostics")
@login_required
def diagnostics():
    return diagnostics_controller.index()

@app.route("/api/diagnostics/run")
@login_required
def run_diagnostics():
    return diagnostics_controller.run_diagnostics()

@app.route("/api/diagnostics/test_run", methods=["POST"])
@login_required
def run_test_pipeline_route():
    return diagnostics_controller.run_test_pipeline()

@app.route("/api/diagnostics/status/<run_id>")
@login_required
def check_run_status(run_id):
    return diagnostics_controller.check_run_status(run_id)

@app.route("/api/diagnostics/cleanup/<run_id>", methods=["POST"])
@login_required
def cleanup_run(run_id):
    return diagnostics_controller.cleanup_run(run_id)

client =OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    message = request.json.get("message", "").strip()
    if not message:
        return jsonify({"reply": "Ask something about the pipeline."})

    prompt = build_prompt(message)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return jsonify({"reply": response.choices[0].message.content})

@app.route("/status_download/<run_id>")
@login_required
def status_download(run_id):
    return redirect(
        url_for(
            "download_output",
            run_id=run_id
        )
    )


@app.route("/download_output/<run_id>")
@login_required
def download_output(run_id):
    return redirect(
        url_for(
            "download_all",
            username=safe_username(session["user"]),
            run_id=run_id
        )
    )


# @app.route("/download-all/<username>/<run_id>")
# @login_required
# def download_all(username, run_id):
#     if username != safe_username(session["user"]) and session.get("role") != "admin":
#         abort(403)

#     zip_path, tmp_dir = create_run_zip(session["user"], run_id)

#     @after_this_request
#     def cleanup(response):
#         shutil.rmtree(tmp_dir, ignore_errors=True)
#         return response

#     return send_file(
#         zip_path,
#         as_attachment=True,
#         download_name=f"{run_id}_results.zip",
#         mimetype="application/zip"
#     )

@app.route("/download-all/<username>/<run_id>")
@login_required
def download_all(username, run_id):
    if username != safe_username(session["user"]) and session.get("role") != "admin":
        abort(403)

    zip_path = get_or_create_run_zip(session["user"], run_id)

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"{run_id}_results.zip",
        mimetype="application/zip",
        conditional=True  # enables browser caching
    )

@app.route("/prepare-download/<run_id>")
@login_required
def prepare_download(run_id):
    # Ensure ZIP exists (this may take time)
    get_or_create_run_zip(session["user"], run_id)

    return jsonify({"ready": True})

@app.route("/download-file/<username>/<run_id>")
@login_required
def download_file(username, run_id):
    if username != safe_username(session["user"]) and session.get("role") != "admin":
        abort(403)

    rel_path = request.args.get("path")
    if not rel_path:
        abort(400)

    base_dir = get_run_dir(session["user"], run_id).resolve()
    file_path = (base_dir / rel_path).resolve()

    if not str(file_path).startswith(str(base_dir)):
        abort(403)

    if not file_path.exists():
        abort(404)

    return send_file(file_path, as_attachment=True)

# =============================
# MY RUNS
# =============================

# @app.route("/my-runs")
# @login_required
# def my_runs():
#     base = Path(PIPELINE_RUNS_DIR) / safe_username(session["user"])
#     runs = []

#     if base.exists():
#         for run in sorted(base.iterdir(), reverse=True):
#             if run.is_dir():
#                 runs.append(run.name)

#     return render_template("my_runs.html", runs=runs)

@app.route("/my-runs")
@login_required
def my_runs():
    username = safe_username(session["user"])
    user_root = Path(PIPELINE_RUNS_DIR) / username
    
    # Fetch DB runs
    conn = get_db_connection()
    db_runs_map = {}
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM pipeline_runs WHERE user_email = %s", (session["user"],))
            rows = cursor.fetchall()
            for r in rows:
                db_runs_map[r["run_id"]] = r
            cursor.close()
            conn.close()
        except:
             pass

    runs_data = []
    
    # 1. Runs in DB
    for run_id, db_data in db_runs_map.items():
         run_path = get_run_dir(session["user"], run_id)
         
         # Check files
         file_tree = {}
         has_files = False
         pipeline_done = False
         pipeline_aborted = False
         
         if run_path.exists():
             has_files = True
             files = [str(p.relative_to(run_path)) for p in run_path.rglob("*") if p.is_file()]
             file_tree = build_file_tree(sorted(files))
             
             # Check for physical status markers
             pipeline_done = (run_path / "PIPELINE_DONE").exists()
             pipeline_aborted = (run_path / "CANCEL").exists()
             
             # Check logs for strict success/failure if markers missing
             log_path = run_path / "pipeline_output.log"
             if log_path.exists():
                 try:
                     with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                         content = f.read()
                         if "PIPELINE FINISHED" in content or "PIPELINE FINISHED SUCCESSFULLY" in content:
                             pipeline_done = True
                         if "PIPELINE ABORTED BY USER" in content:
                             pipeline_aborted = True
                 except:
                     pass

         # SELF-HEALING / SYNC LOGIC
         current_status = db_data["status"]
         new_status = current_status
         
         if pipeline_done and current_status != 'completed':
             new_status = 'completed'
         elif pipeline_aborted and current_status != 'cancelled':
             new_status = 'cancelled'
         
         # Update DB if mismatched
         if new_status != current_status:
             try:
                 # Re-connect to update
                 update_conn = get_db_connection()
                 if update_conn:
                     update_cursor = update_conn.cursor()
                     update_cursor.execute(
                         "UPDATE pipeline_runs SET status = %s, end_time = %s WHERE run_id = %s",
                         (new_status, datetime.now(), run_id)
                     )
                     update_conn.commit()
                     update_cursor.close()
                     update_conn.close()
                     current_status = new_status # Reflect in UI immediately
             except Exception as e:
                 print(f"Failed to sync status for {run_id}: {e}")

         runs_data.append({
             "run_id": run_id,
             "run_type": db_data.get("run_type") or "analysis", # Handle None or missing
             "status": current_status,
             "start_time": db_data["start_time"],
             "end_time": db_data["end_time"],
             "file_tree": file_tree,
             "has_files": has_files
         })

    # 2. Runs on disk NOT in DB (Legacy)
    if user_root.exists():
        for run_dir in user_root.iterdir():
            if run_dir.is_dir() and run_dir.name not in db_runs_map:
                files = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
                runs_data.append({
                    "run_id": run_dir.name,
                    "run_type": "analysis", # Standard pipeline runs (legacy)
                    "status": "legacy",
                    "start_time": datetime.fromtimestamp(run_dir.stat().st_ctime),
                    "end_time": None,
                    "file_tree": build_file_tree(sorted(files)),
                     "has_files": True
                })

    # Sort by start_time
    runs_data.sort(key=lambda x: x["start_time"] if x["start_time"] else datetime.min, reverse=True)

    return render_template("my_runs.html", runs=runs_data, zip=zip)

# =============================
# CANCEL PIPELINE
# =============================

@app.route("/cancel/<run_id>", methods=["POST"])
@login_required
def cancel_run(run_id):
    run_dir = get_run_dir(session["user"], run_id)
    if not run_dir.exists():
        abort(404)

    (run_dir / "CANCEL").write_text("cancelled")

    subprocess.run(
        ["wsl", "--terminate", "Ubuntu"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Log to DB
    main_controller.log_run_end(run_id, 'cancelled')

    flash("Pipeline cancelled.", "info")
    return redirect(url_for("status", run_id=run_id))




@app.route("/fasta-compare", methods=["GET"])
@login_required
def fasta_compare_index():
    return fasta_controller.index()

@app.route("/fasta-compare", methods=["POST"])
@login_required
def fasta_compare_run():
    return fasta_controller.compare()

@app.route("/blast/status/<run_id>")
@login_required
def blast_status(run_id):
    return fasta_controller.blast_status(run_id)

@app.route("/blast/result/<run_id>")
@login_required
def blast_result(run_id):
    return fasta_controller.blast_result(run_id)

@app.route("/api/blast/status/<run_id>")
@login_required
def blast_status_api(run_id):
    return fasta_controller.blast_status_api(run_id)

@app.route("/blast/download_csv/<run_id>")
@login_required
def download_blast_csv(run_id):
    return fasta_controller.download_blast_csv(run_id)
@app.route("/delete_run/<username>/<run_id>", methods=["POST"])
@login_required
def delete_run(username, run_id):
    # Permission check
    if (
        username != safe_username(session["user"])
        and session.get("role") != "admin"
    ):
        abort(403)

    run_dir = get_run_dir(session["user"], run_id)
    if not run_dir.exists():
        abort(404)

    shutil.rmtree(run_dir)

    # Delete from DB
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pipeline_runs WHERE run_id = %s", (run_id,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error deleting from DB: {e}")
    flash("Run deleted successfully.", "success")
    return redirect(url_for("my_runs"))


# =============================
# CONTEXT PROCESSORS
# =============================

@app.context_processor
def inject_helpers():
    return dict(safe_username=safe_username)


@app.context_processor
def inject_user():
    return dict(
        current_user=session.get("user"),
        current_name=session.get("name"),
        current_role=session.get("role")
    )

# =============================
# ENTRY POINT
# =============================

if __name__ == "__main__":
    os.makedirs(PIPELINE_RUNS_DIR, exist_ok=True)
    # Initialize DB table if needed (for dev convenience)
    # Initialize DB table if needed (for dev convenience)
    init_db()

    if os.environ.get("FLASK_ENV") == "development":
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=True,
            threaded=True,
            use_reloader=False
        )
    else:
        from waitress import serve
        print("Starting production server with Waitress on port 5000...")
        # Increase max_request_body_size to 16GB
        serve(app, host="0.0.0.0", port=5000, max_request_body_size=16 * 1024 * 1024 * 1024)
