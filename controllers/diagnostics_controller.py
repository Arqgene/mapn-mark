import os
import subprocess
import json
import logging
from flask import render_template, jsonify, session
from threading import Thread
import uuid
import shutil

from models.newpipeline import run_pipeline_async as run_specific_tool_pipeline


# -------------------------------------------------
# UI
# -------------------------------------------------
def index():
    return render_template("diagnostics.html")


# -------------------------------------------------
# Diagnostics (Native Linux)
# -------------------------------------------------
def run_diagnostics():
    script_path = os.path.abspath(
        os.path.join("pipeline_runs", "scripts", "check_tools.sh")
    )

    if not os.path.exists(script_path):
        return jsonify({"error": "Diagnostics script not found"}), 500

    # Ensure executable
    os.chmod(script_path, 0o755)

    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        if result.returncode != 0:
            return jsonify({
                "error": "Failed to run diagnostics script",
                "details": result.stderr
            }), 500

        # Extract JSON from noisy output
        output = result.stdout
        start_idx = output.find("{")
        end_idx = output.rfind("}")

        if start_idx == -1 or end_idx == -1:
            return jsonify({
                "error": "Invalid output format",
                "raw": output
            }), 500

        data = json.loads(output[start_idx:end_idx + 1])

        # Filter out dummy entry
        tools = [
            t for t in data.get("tools", [])
            if t.get("name") != "System Check"
        ]

        return jsonify({"tools": tools})

    except Exception as e:
        logging.exception("Diagnostics failed")
        return jsonify({"error": str(e)}), 500


# -------------------------------------------------
# TEST PIPELINE LOGIC
# -------------------------------------------------
PIPELINE_RUNS_DIR = "pipeline_runs"
DIAG_DIR = "diag_file"


def safe_username(email: str) -> str:
    return email.replace("@", "_").replace(".", "_")


def get_run_dir(username: str, run_id: str) -> str:
    return os.path.join(
        PIPELINE_RUNS_DIR,
        safe_username(username),
        run_id
    )


def run_test_pipeline():
    if "user" not in session:
        return jsonify({"error": "Login required"}), 403

    if not os.path.exists(DIAG_DIR):
        return jsonify({"error": "'diag_file' directory not found"}), 404

    diag_files = [
        f for f in os.listdir(DIAG_DIR)
        if f.endswith((".fastq", ".fq"))
    ]

    if not diag_files:
        return jsonify({
            "error": "No .fastq file found in 'diag_file' folder"
        }), 404

    input_filename = diag_files[0]
    input_source_path = os.path.join(DIAG_DIR, input_filename)

    username = session["user"]
    run_id = uuid.uuid4().hex[:8]
    session["run_id"] = run_id

    output_dir = get_run_dir(username, run_id)
    os.makedirs(output_dir, exist_ok=True)

    # Copy input FASTQ
    dest_path = os.path.join(output_dir, input_filename)
    shutil.copy2(input_source_path, dest_path)

    params = {
        "input_fastq": dest_path,
        "output_dir": output_dir,
        "genome_size": "5m",
        "threads": "8",
        "output_file": os.path.join(output_dir, "pipeline_output.log"),
        "min_length": "1000",
        "keep_percent": "90",
        "selected_tools": [
            "porechop",
            "filtlong",
            "flye",
            "minimap2",
            "racon",
            "fastqc",
            "prokka",
            "quast"
        ],
        "blast_db_path": ""
    }

    Thread(
        target=run_specific_tool_pipeline,
        kwargs=params,
        daemon=True
    ).start()

    return jsonify({"success": True, "run_id": run_id})


# -------------------------------------------------
# STATUS
# -------------------------------------------------
def check_run_status(run_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    username = session["user"]
    run_dir = get_run_dir(username, run_id)

    if not os.path.exists(run_dir):
        return jsonify({"status": "not_found"}), 404

    if os.path.exists(os.path.join(run_dir, "PIPELINE_DONE")):
        status = "success"
    elif os.path.exists(os.path.join(run_dir, "PIPELINE_ABORTED")):
        status = "failed"
    elif os.path.exists(os.path.join(run_dir, "CANCEL")):
        status = "cancelled"
    else:
        status = "running"

    return jsonify({"status": status})


# -------------------------------------------------
# CLEANUP
# -------------------------------------------------
def cleanup_run(run_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    username = session["user"]
    run_dir = get_run_dir(username, run_id)

    if os.path.exists(run_dir):
        try:
            shutil.rmtree(run_dir)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"success": True})
