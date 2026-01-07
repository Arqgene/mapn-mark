import os
import subprocess
import uuid
import datetime
import csv
import tempfile
import shutil

# Default to "blast_db/reference" relative to project root
BLAST_DB_PATH = os.path.join(os.getcwd(), "blast_db", "reference")

# -------------------------------------------------
# Debug helper
# -------------------------------------------------
def debug(msg):
    print(f"[PY-DEBUG {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

# -------------------------------------------------
# Convert Windows → WSL path
# -------------------------------------------------
def convert_to_wsl_path(win_path):
    win_path = os.path.abspath(win_path)
    # Check existence only if it's not a potential new file path (like an output log)
    # But for input files it's good. 
    # For now, we'll skip strict existence check for output paths or make sure we pass existing dirs.
    
    drive, path = os.path.splitdrive(win_path)
    drive_letter = drive.rstrip(":").lower()
    linux_path = path.replace("\\", "/").lstrip("/")
    return f"/mnt/{drive_letter}/{linux_path}"

# -------------------------------------------------
# Run bash script inside WSL
# -------------------------------------------------
def run_script_in_wsl(script_contents, output_file):
    script_dir = os.path.join("pipeline_runs", "scripts")
    os.makedirs(script_dir, exist_ok=True)

    script_path = os.path.join(script_dir, f"{uuid.uuid4()}.sh")
    with open(script_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(script_contents)

    wsl_script_path = convert_to_wsl_path(script_path)
    
    # Ensure script is executable
    subprocess.run(["wsl", "chmod", "+x", wsl_script_path], check=True)

    with open(output_file, "a", encoding="utf-8") as logf:
        process = subprocess.Popen(
            ["wsl", "bash", wsl_script_path],
            stdout=logf,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        ret = process.wait()
        if ret != 0:
            raise RuntimeError(f"BLAST pipeline aborted (exit code {ret})")

# -------------------------------------------------
# BLAST Pipeline Function (Reference-Style)
# -------------------------------------------------
def run_blast_pipeline(
    query_fasta,          # FASTA file to query
    output_dir,           # Output directory
    blast_db_path,        # BLAST DB (prefix, no extension)
    threads,
    output_file,
    blast_task="blastn",   # changed default to blastn, user can override to blastn-fast
    max_hits=10
):
    debug("Starting BLAST pipeline")

    query_fasta_wsl = convert_to_wsl_path(query_fasta)
    output_dir_wsl = convert_to_wsl_path(output_dir)
    blast_db_wsl = convert_to_wsl_path(blast_db_path)

    script = f"""#!/usr/bin/env bash
set -euo pipefail

QUERY_FASTA="{query_fasta_wsl}"
OUTPUT_DIR="{output_dir_wsl}"
BLAST_DB="{blast_db_wsl}"
THREADS="{threads}"
MAX_HITS="{max_hits}"

# LOG_FILE="$OUTPUT_DIR/blast.log"
# mkdir -p "$OUTPUT_DIR"
# Unnecessary to touch log file here, python handles it via stdout capture

# Redirect stderr to stdout, but NO TEE to file (Python captures stdout)
exec 2>&1

log() {{
    echo "[BLAST $(date '+%H:%M:%S')] $1"
}}

run_with_cancel() {{
    CMD="$1"
    log "RUNNING: $CMD"
    bash -c "$CMD"
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        log "BLAST ABORTED (exit code $EXIT_CODE)"
        touch "$OUTPUT_DIR/BLAST_ABORTED"
        exit $EXIT_CODE
    fi
}}

log "BLAST pipeline started"
log "Query FASTA: $QUERY_FASTA"
log "BLAST DB: $BLAST_DB"

# -------------------------------------------------
# Conda activation (same as main pipeline)
# -------------------------------------------------
for p in "$HOME/miniconda3/bin" "$HOME/anaconda3/bin"; do
    [ -d "$p" ] && export PATH="$p:$PATH"
done

if command -v conda &>/dev/null; then
    BASE=$(conda info --base 2>/dev/null)
    [ -f "$BASE/etc/profile.d/conda.sh" ] && source "$BASE/etc/profile.d/conda.sh"
    # Try multiple env names or fallback to base if needed, currently assumes 'pipeline'
    conda activate pipeline || conda activate base || log "Conda env not found, using system PATH"
fi

# -------------------------------------------------
# BLAST DB validation
# -------------------------------------------------
# Check for any common extension
FOUND_DB=0
for ext in .nin .nsq .nhr .nal; do
    if [ -f "$BLAST_DB$ext" ]; then
        FOUND_DB=1
        break
    fi
done

if [ $FOUND_DB -eq 0 ]; then
    log "ERROR: Missing BLAST DB files at $BLAST_DB"
    # List directory for debugging
    ls -la "$(dirname "$BLAST_DB")"
    exit 1
fi

# -------------------------------------------------
# BLAST execution
# -------------------------------------------------
log "STEP: blastn"

run_with_cancel "blastn \\
    -task {blast_task} \\
    -query '$QUERY_FASTA' \\
    -db '$BLAST_DB' \\
    -num_threads '$THREADS' \\
    -max_target_seqs '$MAX_HITS' \\
    -max_hsps 1 \\
    -outfmt '6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore' \\
    -out '$OUTPUT_DIR/blast_results.tsv'"

touch "$OUTPUT_DIR/BLAST_DONE"
log "BLAST pipeline finished successfully"
"""

    try:
        run_script_in_wsl(script, output_file)
    except Exception as e:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"\\n[INTERNAL ERROR] {str(e)}\\n")
        raise

# -------------------------------------------------
# Compatibility Wrapper for Controller
# -------------------------------------------------
def run_blast(query_fasta_content: str):
    """
    Wrapper to maintain compatibility with the existing controller.
    Creates a temporary directory, runs the pipeline, parses results, and cleans up.
    """
    # Create a persistent temp directory for this run
    # (We can't use standard tempfile.TemporaryDirectory easily if we want to debug logs later)
    # Using a timestamped folder in 'pipeline_runs/blast_adhoc'
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    base_dir = os.path.join(os.getcwd(), "pipeline_runs", "blast_adhoc", run_id)
    os.makedirs(base_dir, exist_ok=True)
    
    query_file = os.path.join(base_dir, "query.fasta")
    log_file = os.path.join(base_dir, "pipeline.log")
    
    # Write query content
    with open(query_file, "w", encoding="utf-8") as f:
        f.write(query_fasta_content)
        
    try:
        run_blast_pipeline(
            query_fasta=query_file,
            output_dir=base_dir,
            blast_db_path=BLAST_DB_PATH,
            threads=4,
            output_file=log_file,
            blast_task="blastn" # Use standard blastn for better accuracy on gene comparison
        )
        
        # Parse results
        result_file = os.path.join(base_dir, "blast_results.tsv")
        results = []
        if os.path.exists(result_file):
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
        return results

    except Exception as e:
        print(f"BLAST Pipeline Failed. See logs at {base_dir}")
        # Re-raise so controller can handle/flash it
        # Or return empty? Controller expects exceptions for flashing errors.
        raise e
