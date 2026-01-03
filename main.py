from flask import (
    Flask, redirect, url_for, send_file,
    abort, request, render_template,
    flash, session, jsonify, after_this_request
)
from controllers import main_controller, diagnostics_controller
from models.db import get_user_by_email, init_db, update_user_session_token
from ai.chat_engine import build_prompt
from openai import OpenAI

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

# =============================
# APP CONFIG
# =============================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_key_fallback_do_not_use_in_prod")

PIPELINE_RUNS_DIR = "pipeline_runs"

# =============================
# DEMO USER DATABASE
# =============================

# =============================
# DEMO USER DATABASE
# =============================

# Users are now managed via MySQL database


# =============================
# HELPERS
# =============================

def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")


def get_run_dir(email: str, run_id: str) -> Path:
    return Path(PIPELINE_RUNS_DIR) / safe_username(email) / run_id


# =============================
# LOGIN REQUIRED DECORATOR
# =============================

# =============================
# SESSION MANAGEMENT (Idle Timeout + Logout on Close)
# =============================
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

# =============================
# AUTH ROUTES
# =============================

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

# =============================
# SAFE ZIP CREATION
# =============================

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

    # ZIP already exists → reuse
    if zip_path.exists():
        return zip_path

    # Create ZIP once
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in run_dir.rglob("*"):
            if file.is_file() and file.name != zip_path.name:
                zipf.write(file, file.relative_to(run_dir))

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

# =============================
# CORE ROUTES
# =============================

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

# =============================
# AI CHAT
# =============================

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

# =============================
# DOWNLOAD ROUTES
# =============================
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

# =============================
# FILE DOWNLOAD (SINGLE FILE)
# =============================

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
    runs = []
    base_root = Path(PIPELINE_RUNS_DIR)

    user_root = base_root / safe_username(session["user"])

    if not user_root.exists():
        return render_template("my_runs.html", runs=[])

    for run_dir in sorted(user_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue

        files = [
            str(p.relative_to(run_dir))
            for p in run_dir.rglob("*")
            if p.is_file()
        ]

        runs.append({
            "username": safe_username(session["user"]),
            "run_id": run_dir.name,
            "file_tree": build_file_tree(sorted(files))
        })

    return render_template("my_runs.html", runs=runs)

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

    flash("Pipeline cancelled.", "info")
    return redirect(url_for("status", run_id=run_id))



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
        serve(app, host="0.0.0.0", port=5000)
