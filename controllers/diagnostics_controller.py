import os
import subprocess
import json
import logging
from flask import render_template, jsonify
from models.newpipeline import convert_to_wsl_path

def index():
    return render_template("diagnostics.html")

def run_diagnostics():
    script_path = os.path.abspath(os.path.join("pipeline_runs", "scripts", "check_tools.sh"))
    wsl_path = convert_to_wsl_path(script_path)
    
    # Ensure executable
    subprocess.run(["wsl", "chmod", "+x", wsl_path], capture_output=True)

    try:
        result = subprocess.run(
            ["wsl", "bash", wsl_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            return jsonify({"error": "Failed to run diagnostics script", "details": result.stderr}), 500

        # Parse JSON output
        # The script outputs JSON. We need to be careful of potential noise (warnings etc).
        # We'll try to find the first '{' and last '}'
        output = result.stdout
        start_idx = output.find('{')
        end_idx = output.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
             return jsonify({"error": "Invalid output format", "raw": output}), 500
             
        json_str = output[start_idx:end_idx+1]
        data = json.loads(json_str)
        
        # Filter out the dummy "System Check" entry
        tools = [t for t in data.get("tools", []) if t["name"] != "System Check"]
        
        return jsonify({"tools": tools})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# TEST PIPELINE LOGIC
# -----------------------------
import uuid
import shutil
from threading import Thread
from flask import session, url_for
from models.newpipeline import run_pipeline_async as run_specific_tool_pipeline

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

    # Check for input file
    diag_files = [f for f in os.listdir(DIAG_DIR) if f.endswith(('.fastq', '.fq'))]
    if not diag_files:
        return jsonify({"error": "No .fastq file found in 'diag_file' folder"}), 404
    
    input_filename = diag_files[0]
    input_source_path = os.path.join(DIAG_DIR, input_filename)

    # Setup Run
    username = session["user"]
    run_id = uuid.uuid4().hex[:8]
    session["run_id"] = run_id
    output_dir = get_run_dir(username, run_id)
    os.makedirs(output_dir, exist_ok=True)

    # Copy input file
    dest_path = os.path.join(output_dir, input_filename)
    shutil.copy2(input_source_path, dest_path)

    # Default Parameters for Test
    params = {
        "input_fastq": dest_path,
        "output_dir": output_dir,
        "genome_size": "5m",
        "threads": "8",
        "output_file": os.path.join(output_dir, "pipeline_output.log"),
        "min_length": "1000",
        "keep_percent": "90",
        "selected_tools": ["porechop", "filtlong", "flye", "minimap2", "racon", "fastqc", "prokka", "quast"],
        "blast_db_path": ""
    }

    # Launch Pipeline
    Thread(
        target=run_specific_tool_pipeline,
        kwargs=params
    ).start()

    return jsonify({"success": True, "run_id": run_id})

def check_run_status(run_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
        
    username = session["user"]
    run_dir = get_run_dir(username, run_id)
    
    if not os.path.exists(run_dir):
        return jsonify({"status": "not_found"}), 404
        
    status = "running"
    if os.path.exists(os.path.join(run_dir, "PIPELINE_DONE")):
        status = "success"
    elif os.path.exists(os.path.join(run_dir, "PIPELINE_ABORTED")):
        status = "failed"
    elif os.path.exists(os.path.join(run_dir, "CANCEL")):
        status = "cancelled"
        
    return jsonify({"status": status})

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
    
    return jsonify({"success": True}) # Already gone is a success
