import os
import shutil
from flask import Blueprint, render_template, session, redirect, url_for, flash

files_bp = Blueprint("files", __name__)

PIPELINE_RUNS_DIR = "pipeline_runs"


def get_user_runs(user_id):
    runs = []
    base = os.path.join(PIPELINE_RUNS_DIR, user_id)

    if not os.path.exists(base):
        return runs

    for run_id in sorted(os.listdir(base), reverse=True):
        run_path = os.path.join(base, run_id)
        if not os.path.isdir(run_path):
            continue

        files = []
        for root, _, filenames in os.walk(run_path):
            for f in filenames:
                files.append({
                    "name": f,
                    "path": os.path.relpath(os.path.join(root, f), run_path)
                })

        runs.append({
            "run_id": run_id,
            "files": files
        })

    return runs


@files_bp.route("/my-runs")
def my_runs():
    if "user_id" not in session:
        flash("Login required", "error")
        return redirect(url_for("login"))

    runs = get_user_runs(str(session["user_id"]))
    return render_template("my_runs.html", runs=runs)


@files_bp.route("/delete-run/<run_id>", methods=["POST"])
def delete_run(run_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    run_path = os.path.join(
        PIPELINE_RUNS_DIR,
        str(session["user_id"]),
        run_id
    )

    if os.path.exists(run_path):
        shutil.rmtree(run_path)
        flash("Pipeline run deleted successfully", "success")
    else:
        flash("Run not found", "error")

    return redirect(url_for("files.my_runs"))
