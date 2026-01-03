import os
import subprocess
import uuid
import datetime


# -------------------------------------------------
# Python-side debug (Flask console only)
# -------------------------------------------------
def debug(msg):
    print(f"[PY-DEBUG {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# -------------------------------------------------
# Convert Windows → WSL path
# -------------------------------------------------
def convert_to_wsl_path(win_path):
    win_path = os.path.abspath(win_path)
    if not os.path.exists(win_path):
        raise FileNotFoundError(f"Path does not exist: {win_path}")

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
            raise RuntimeError(f"Pipeline aborted with exit code {ret}")


# -------------------------------------------------
# MAIN PIPELINE
# -------------------------------------------------
def run_pipeline_async(
    input_fastq,
    output_dir,
    genome_size,
    threads,
    output_file,
    min_length,
    keep_percent,
    selected_tools,
    blast_db_path=""
):
    debug(f"Enabled tools: {selected_tools}")

    input_fastq_wsl = convert_to_wsl_path(input_fastq)
    output_dir_wsl = convert_to_wsl_path(output_dir)
    blast_db_wsl = convert_to_wsl_path(blast_db_path) if blast_db_path else ""

    script = f"""#!/usr/bin/env bash
set -euo pipefail

INPUT_FASTQ="{input_fastq_wsl}"
OUTPUT_DIR="{output_dir_wsl}"
GENOME_SIZE="{genome_size}"
THREADS="{threads}"
MIN_LENGTH="{min_length}"
KEEP_PERCENT="{keep_percent}"
BLAST_DB_PATH="{blast_db_wsl}"

LOG_FILE="$OUTPUT_DIR/pipeline.log"
mkdir -p "$OUTPUT_DIR"
touch "$LOG_FILE"

exec > >(stdbuf -oL tr '\\r' '\\n' | tee -a "$LOG_FILE") 2>&1

log() {{
    echo "[PIPELINE $(date '+%H:%M:%S')] $1"
}}

run_with_cancel() {{
    CMD="$1"
    log "RUNNING: $CMD"
    bash -c "$CMD"
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        log "PIPELINE ABORTED (exit code $EXIT_CODE)"
        touch "$OUTPUT_DIR/PIPELINE_ABORTED"
        exit $EXIT_CODE
    fi
}}

log "Pipeline started"
log "Input FASTQ: $INPUT_FASTQ"

# -------------------------------------------------
# Conda activation
# -------------------------------------------------
for p in "$HOME/miniconda3/bin" "$HOME/anaconda3/bin"; do
    [ -d "$p" ] && export PATH="$p:$PATH"
done

if command -v conda &>/dev/null; then
    BASE=$(conda info --base 2>/dev/null)
    [ -f "$BASE/etc/profile.d/conda.sh" ] && source "$BASE/etc/profile.d/conda.sh"
    conda activate pipeline || log "Conda env not found"
fi

CURRENT_FASTQ="$INPUT_FASTQ"
CURRENT_FASTA=""
CURRENT_FILE="$INPUT_FASTQ"
"""

    # ---------------- PORECHOP ----------------
    if "porechop" in selected_tools:
        script += """
log "STEP: Porechop"
mkdir -p "$OUTPUT_DIR/porechop"
run_with_cancel "porechop -i '$CURRENT_FASTQ' -o '$OUTPUT_DIR/porechop/trimmed.fastq'"
CURRENT_FASTQ="$OUTPUT_DIR/porechop/trimmed.fastq"
"""

    # ---------------- DEDUP + FILTLONG ----------------
    if "filtlong" in selected_tools:
        script += """
log "STEP: Deduplication (SRA-safe)"
mkdir -p "$OUTPUT_DIR/dedup"

if command -v seqkit &>/dev/null; then
    run_with_cancel "seqkit rename '$CURRENT_FASTQ' -o '$OUTPUT_DIR/dedup/dedup.fastq'"
    CURRENT_FASTQ="$OUTPUT_DIR/dedup/dedup.fastq"
else
    log "PIPELINE ABORTED: seqkit not found"
    exit 1
fi

log "STEP: Filtlong"
mkdir -p "$OUTPUT_DIR/filtlong"
run_with_cancel "filtlong --min_length '$MIN_LENGTH' --keep_percent '$KEEP_PERCENT' \
    '$CURRENT_FASTQ' > '$OUTPUT_DIR/filtlong/filtered.fastq'"

CURRENT_FASTQ="$OUTPUT_DIR/filtlong/filtered.fastq"
"""

    # ---------------- FLYE ----------------
    if "flye" in selected_tools:
        script += """
log "STEP: Flye"
mkdir -p "$OUTPUT_DIR/flye"
run_with_cancel "flye --nano-raw '$CURRENT_FASTQ' \
    --out-dir '$OUTPUT_DIR/flye' \
    --threads '$THREADS' \
    --genome-size '$GENOME_SIZE'"

CURRENT_FASTA="$OUTPUT_DIR/flye/assembly.fasta"
"""

    # ---------------- MINIMAP2 ----------------
    if "minimap2" in selected_tools:
        script += """
log "STEP: Minimap2"
mkdir -p "$OUTPUT_DIR/minimap2"
run_with_cancel "minimap2 -t '$THREADS' -x map-ont \
    '$CURRENT_FASTA' '$CURRENT_FASTQ' > '$OUTPUT_DIR/minimap2/reads.paf'"
"""

    # ---------------- RACON ----------------
    if "racon" in selected_tools:
        script += """
log "STEP: Racon"
mkdir -p "$OUTPUT_DIR/racon"
run_with_cancel "racon -t '$THREADS' \
    '$CURRENT_FASTQ' \
    '$OUTPUT_DIR/minimap2/reads.paf' \
    '$CURRENT_FASTA' > '$OUTPUT_DIR/racon/polished.fasta'"

CURRENT_FILE="$OUTPUT_DIR/racon/polished.fasta"
"""

    # ---------------- FASTQC ----------------
    if "fastqc" in selected_tools:
        script += """
log "STEP: FastQC"
mkdir -p "$OUTPUT_DIR/fastqc/raw" "$OUTPUT_DIR/fastqc/filtered"
run_with_cancel "fastqc '$INPUT_FASTQ' -o '$OUTPUT_DIR/fastqc/raw'"
run_with_cancel "fastqc '$CURRENT_FASTQ' -o '$OUTPUT_DIR/fastqc/filtered'"
"""

    # ---------------- PROKKA ----------------
    if "prokka" in selected_tools:
        script += """
log "STEP: Prokka"
mkdir -p "$OUTPUT_DIR/prokka"
run_with_cancel "prokka --outdir '$OUTPUT_DIR/prokka' \
    --force \
    --prefix genome '$CURRENT_FILE'"
"""

    # ---------------- QUAST ----------------
    if "quast" in selected_tools:
        script += """
log "STEP: QUAST"
mkdir -p "$OUTPUT_DIR/quast"
run_with_cancel "quast '$CURRENT_FILE' -o '$OUTPUT_DIR/quast'"
"""

    script += """
touch "$OUTPUT_DIR/PIPELINE_DONE"
log "PIPELINE FINISHED SUCCESSFULLY"
"""

    try:
        run_script_in_wsl(script, output_file)
    except Exception as e:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"\n[INTERNAL ERROR] {str(e)}\n")
        print(f"Pipeline failed: {e}")
