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
import signal
import psutil
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv
import threading

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
app.config['SESSION_PERMANENT'] = False

@app.before_request
def make_session_permanent():
    session.permanent = False
    app.permanent_session_lifetime = timedelta(minutes=30)

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

        # 2. Concurrent Session Check
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
        email_or_username = request.form.get("email")
        password = request.form.get("password")

        if not email_or_username or not password:
             flash("Please provide email/username and password.", "error")
        else:
            user = get_user_by_email(email_or_username)
            if not user:
                 conn = get_db_connection()
                 if conn:
                     cursor = conn.cursor(dictionary=True)
                     cursor.execute("SELECT * FROM users WHERE username = %s", (email_or_username,))
                     user = cursor.fetchone()
                     cursor.close()
                     conn.close()

            if user and user["password"] == password:
                new_token = uuid.uuid4().hex
                update_user_session_token(user["email"], new_token)
                
                session["user"] = user["email"]
                session["name"] = user["name"]
                session["role"] = user["role"]
                session["institution_id"] = user.get("institution_id") 
                session["token"] = new_token
                session["last_active"] = datetime.now().timestamp()
                
                # License Check Logic
                if user.get("institution_id"):
                     conn = get_db_connection()
                     if conn:
                         cursor = conn.cursor(dictionary=True)
                         cursor.execute("SELECT * FROM institutions WHERE id = %s", (user["institution_id"],))
                         inst = cursor.fetchone()
                         cursor.close()
                         conn.close()
                         
                         if inst and inst.get('license_expiry'):
                             expiry = inst['license_expiry']
                             if isinstance(expiry, str):
                                 try:
                                     expiry = datetime.strptime(expiry, '%Y-%m-%d').date()
                                 except:
                                     pass
                             
                             today = datetime.now().date()
                             
                             if expiry < today:
                                 session.clear()
                                 flash("Your institution's license has expired. Please contact support.", "error")
                                 return redirect(url_for("login"))
                             
                             days_left = (expiry - today).days
                             if days_left <= 7:
                                 flash(f"Warning: License expires in {days_left} days. Please renew.", "warning")

                flash("Login successful.", "success")
                
                if user['role'] == 'admin':
                    return redirect(url_for("create_user"))
                else:
                    return redirect(url_for("index"))

            flash("Invalid credentials.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/super-admin-dashboard")
@login_required
def super_admin_dashboard():
    if session.get("role") != "super_admin":
        abort(403)
    return render_template("super_admin_dashboard.html")


@app.route("/create-user")
@login_required
def create_user():
    if session.get("role") not in ["admin", "super_admin"]:
        abort(403)
    return render_template("create_user.html")

@app.route("/api/institutions", methods=["GET"])
@login_required
def api_get_institutions():
    if session.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM institutions")
            insts = cursor.fetchall()
            return jsonify(insts)
        finally:
            conn.close()
    return jsonify({"error": "DB Error"}), 500

@app.route("/api/create-institution", methods=["POST"])
@login_required
def api_create_institution():
    if session.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    name = data.get("name")
    user_limit = int(data.get("user_limit", 10))
    admin_limit = int(data.get("admin_limit", 1))
    license_expiry = data.get("license_expiry")

    if not name:
        return jsonify({"error": "Institution name is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM institutions WHERE name = %s", (name,))
        if cursor.fetchone():
            return jsonify({"error": "Institution already exists"}), 409

        cursor.execute(
            "INSERT INTO institutions (name, user_limit, admin_limit, license_expiry) VALUES (%s, %s, %s, %s)",
            (name, user_limit, admin_limit, license_expiry)
        )
        conn.commit()
        return jsonify({"message": "Institution created successfully"}), 201

    except Exception as e:
        print(f"Error creating institution: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/renew-license", methods=["POST"])
@login_required
def api_renew_license():
    if session.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    inst_id = data.get("institution_id")
    new_expiry = data.get("new_expiry")

    if not inst_id or not new_expiry:
        return jsonify({"error": "Institution ID and New Expiry Date are required"}), 400

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE institutions SET license_expiry = %s WHERE id = %s", (new_expiry, inst_id))
            conn.commit()
            return jsonify({"message": "License renewed successfully"}), 200
        except Exception as e:
            print(f"Error renewing license: {e}")
            return jsonify({"error": "Internal Error"}), 500
        finally:
            cursor.close()
            conn.close()
    return jsonify({"error": "DB Error"}), 500


@app.route("/api/delete-institution", methods=["POST"])
@login_required
def api_delete_institution():
    if session.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    inst_id = data.get("institution_id")

    if not inst_id:
        return jsonify({"error": "Institution ID is required"}), 400

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM institutions WHERE id = %s", (inst_id,))
            conn.commit()
            return jsonify({"message": "Institution deleted successfully"}), 200
        except Exception as e:
            print(f"Error deleting institution: {e}")
            return jsonify({"error": "Internal Error"}), 500
        finally:
            cursor.close()
            conn.close()
    return jsonify({"error": "DB Error"}), 500


@app.route("/api/create-user", methods=["POST"])
@login_required
def api_create_user():
    current_role = session.get("role")
    current_inst_id = session.get("institution_id")
    
    if current_role not in ["admin", "super_admin"]:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")
    name = data.get("name")
    target_role = data.get("role", "user")
    
    target_inst_id = data.get("institution_id") 
    new_inst_name = data.get("new_institution_name")
    new_user_limit = int(data.get("user_limit", 10))
    new_admin_limit = int(data.get("admin_limit", 1))

    if not all([email, username, password, name]):
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        if current_role != "super_admin":
            if target_role == "super_admin":
                return jsonify({"error": "You cannot create Super Admins."}), 403
            
            target_inst_id = current_inst_id
            
            if new_inst_name:
                return jsonify({"error": "Only Super Admins can create institutions."}), 403
        else:
            if target_role == "super_admin":
                 if not (session.get("user") and session.get("role") == "super_admin"):
                     return jsonify({"error": "Only Super Admins can create Super Admins."}), 403
                 target_inst_id = None

        if new_inst_name:
            cursor.execute("SELECT id FROM institutions WHERE name = %s", (new_inst_name,))
            if cursor.fetchone():
                return jsonify({"error": f"Institution '{new_inst_name}' already exists."}), 409
            
            cursor.execute("INSERT INTO institutions (name, user_limit, admin_limit) VALUES (%s, %s, %s)", 
                           (new_inst_name, new_user_limit, new_admin_limit))
            target_inst_id = cursor.lastrowid
            conn.commit()

        if target_inst_id:
            cursor.execute("SELECT * FROM institutions WHERE id = %s", (target_inst_id,))
            inst = cursor.fetchone()
            if not inst:
                return jsonify({"error": "Invalid Institution ID"}), 400
            
            if target_role == "user":
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE institution_id = %s AND role = 'user'", (target_inst_id,))
                count = cursor.fetchone()['count']
                if count >= inst['user_limit']:
                     return jsonify({"error": f"User seat limit reached for {inst['name']} ({inst['user_limit']} max)."}), 409
            
            elif target_role == "admin":
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE institution_id = %s AND role = 'admin'", (target_inst_id,))
                count = cursor.fetchone()['count']
                if count >= inst['admin_limit']:
                     return jsonify({"error": f"Admin seat limit reached for {inst['name']} ({inst['admin_limit']} max)."}), 409

        cursor.execute("SELECT id FROM users WHERE email = %s OR username = %s", (email, username))
        if cursor.fetchone():
            return jsonify({"error": "User with this email or username already exists"}), 409

        cursor.execute(
            "INSERT INTO users (email, username, password, name, role, institution_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (email, username, password, name, target_role, target_inst_id)
        )
        conn.commit()
        return jsonify({"message": "User created successfully"}), 201

    except Exception as e:
        print(f"Error creating user: {e}")
        return jsonify({"error": f"Internal Error: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/users", methods=["GET"])
@login_required
def api_get_users():
    current_role = session.get("role")
    current_inst_id = session.get("institution_id")
    
    if current_role not in ["admin", "super_admin"]:
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            
            if current_role == "super_admin":
                query = """
                SELECT u.id, u.name, u.email, u.username, u.role, u.institution_id, i.name as institution_name 
                FROM users u 
                LEFT JOIN institutions i ON u.institution_id = i.id
                WHERE u.email != %s
                """
                cursor.execute(query, (session["user"],))
            else:
                query = """
                SELECT u.id, u.name, u.email, u.username, u.role, u.institution_id, i.name as institution_name
                FROM users u
                LEFT JOIN institutions i ON u.institution_id = i.id
                WHERE u.institution_id = %s AND u.email != %s
                """
                cursor.execute(query, (current_inst_id, session["user"]))
                
            users = cursor.fetchall()
            
            inst_stats = {}
            if current_role != "super_admin" and current_inst_id:
                 cursor.execute("SELECT * FROM institutions WHERE id=%s", (current_inst_id,))
                 inst = cursor.fetchone()
                 if inst:
                     cursor.execute("SELECT role, COUNT(*) as c FROM users WHERE institution_id=%s GROUP BY role", (current_inst_id,))
                     counts = {row['role']: row['c'] for row in cursor.fetchall()}
                     inst_stats = {
                         "user_limit": inst['user_limit'],
                         "admin_limit": inst['admin_limit'],
                         "user_count": counts.get('user', 0),
                         "admin_count": counts.get('admin', 0)
                     }

            return jsonify({"users": users, "stats": inst_stats})

        except Exception as e:
            print(f"Error fetching users: {e}")
            return jsonify({"error": "Internal database error"}), 500
        finally:
            cursor.close()
            conn.close()
    
    return jsonify({"error": "Database connection failed"}), 500

@app.route("/api/delete-user", methods=["POST"])
@login_required
def api_delete_user():
    current_role = session.get("role")
    current_inst_id = session.get("institution_id")

    if current_role not in ["admin", "super_admin"]:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    email_to_delete = data.get("email")

    if not email_to_delete:
        return jsonify({"error": "Email is required"}), 400

    if email_to_delete == session.get("user"):
        return jsonify({"error": "You cannot delete your own account while logged in."}), 400

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT id, role, institution_id FROM users WHERE email = %s", (email_to_delete,))
            target = cursor.fetchone()
            
            if not target:
                return jsonify({"error": "User not found"}), 404

            if current_role != "super_admin":
                if target['institution_id'] != current_inst_id:
                    return jsonify({"error": "Unauthorized: User belongs to another institution."}), 403
                
                if target['role'] == "super_admin":
                     return jsonify({"error": "You cannot delete Super Admins."}), 403

            cursor.execute("DELETE FROM users WHERE email = %s", (email_to_delete,))
            conn.commit()
            
            return jsonify({"message": f"User {email_to_delete} deleted successfully"}), 200

        except Exception as e:
            print(f"Error deleting user: {e}")
            return jsonify({"error": "Internal database error"}), 500
        finally:
            cursor.close()
            conn.close()
    
    return jsonify({"error": "Database connection failed"}), 500

def get_or_create_run_zip(email: str, run_id: str) -> Path:
    run_dir = get_run_dir(email, run_id)
    if not run_dir.exists():
        abort(404, "Run not found")

    zip_path = run_dir / f"{run_id}.zip"

    if zip_path.exists():
        if zipfile.is_zipfile(zip_path):
            return zip_path
        else:
            print(f"Corrupt zip found at {zip_path}, regenerating...")
            try:
                os.remove(zip_path)
            except OSError:
                pass

    tmp_zip_path = run_dir / f"{run_id}.zip.tmp"
    
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in run_dir.rglob("*"):
                if file.is_file() and file.name != zip_path.name and not file.name.endswith('.tmp'):
                    zipf.write(file, file.relative_to(run_dir))
        
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
    if session.get("role") == "admin":
        return redirect(url_for("create_user"))
    return main_controller.index()


@app.route("/status/<run_id>")
@login_required
def status(run_id):
    if session.get("role") == "admin":
        return redirect(url_for("create_user"))
    return main_controller.status(run_id)


@app.route("/get_log/<run_id>")
@login_required
def get_log(run_id):
    if session.get("role") == "admin":
        return redirect(url_for("create_user"))
    return main_controller.get_log(run_id)

@app.route("/diagnostics")
@login_required
def diagnostics():
    if session.get("role") == "admin":
        return redirect(url_for("create_user"))
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

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
        conditional=True
    )

@app.route("/prepare-download/<run_id>")
@login_required
def prepare_download(run_id):
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

@app.route("/my-runs")
@login_required
def my_runs():
    if session.get("role") == "admin":
        return redirect(url_for("create_user"))
    username = safe_username(session["user"])
    
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
         
         file_tree = {}
         has_files = False
         pipeline_done = False
         pipeline_aborted = False
         
         if run_path.exists():
             has_files = True
             files = [str(p.relative_to(run_path)) for p in run_path.rglob("*") if p.is_file()]
             file_tree = build_file_tree(sorted(files))
             
             pipeline_done = (run_path / "PIPELINE_DONE").exists()
             pipeline_aborted = (run_path / "CANCEL").exists()
             
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

         current_status = db_data["status"]
         new_status = current_status
         
         if pipeline_done and current_status != 'completed':
             new_status = 'completed'
         elif pipeline_aborted and current_status != 'cancelled':
             new_status = 'cancelled'
         
         if new_status != current_status:
             try:
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
                     current_status = new_status
             except Exception as e:
                 print(f"Failed to sync status for {run_id}: {e}")

         runs_data.append({
             "run_id": run_id,
             "run_type": db_data.get("run_type") or "analysis",
             "status": current_status,
             "start_time": db_data["start_time"],
             "end_time": db_data["end_time"],
             "file_tree": file_tree,
             "has_files": has_files
         })

    # 2. Legacy runs
    user_root = Path(PIPELINE_RUNS_DIR) / username
    if user_root.exists():
        for run_dir in user_root.iterdir():
            if run_dir.is_dir() and run_dir.name not in db_runs_map:
                files = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
                runs_data.append({
                    "run_id": run_dir.name,
                    "run_type": "analysis",
                    "status": "legacy",
                    "start_time": datetime.fromtimestamp(run_dir.stat().st_ctime),
                    "end_time": None,
                    "file_tree": build_file_tree(sorted(files)),
                     "has_files": True
                })

    runs_data.sort(key=lambda x: x["start_time"] if x["start_time"] else datetime.min, reverse=True)

    return render_template("my_runs.html", runs=runs_data, zip=zip)

def kill_process_tree(pid):
    """Kill a process and all its children recursively"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except:
                pass
        
        parent.terminate()
        
        gone, alive = psutil.wait_procs([parent] + children, timeout=5)
        
        for p in alive:
            try:
                p.kill()
            except:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        print(f"Error killing process tree: {e}")

@app.route("/cancel/<run_id>", methods=["POST"])
@login_required
def cancel_run(run_id):
    run_dir = get_run_dir(session["user"], run_id)
    if not run_dir.exists():
        abort(404)

    # Create cancel flag
    (run_dir / "CANCEL").write_text("cancelled")

    # Try to find and kill running pipeline processes
    pid_file = run_dir / "pipeline.pid"
    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
                kill_process_tree(pid)
        except Exception as e:
            print(f"Error killing process from PID file: {e}")

    # Also look for running subprocesses
    try:
        # Find processes that might be running the pipeline
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any(run_id in str(arg) for arg in cmdline):
                    kill_process_tree(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        print(f"Error searching for pipeline processes: {e}")

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
    if (
        username != safe_username(session["user"])
        and session.get("role") != "admin"
    ):
        abort(403)

    run_dir = get_run_dir(session["user"], run_id)
    if not run_dir.exists():
        abort(404)

    shutil.rmtree(run_dir)

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
        serve(app, host="0.0.0.0", port=5000, max_request_body_size=16 * 1024 * 1024 * 1024)
