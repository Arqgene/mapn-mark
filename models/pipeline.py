import os
import subprocess
import uuid
import datetime


# -------------------------------------------------
# Python-side debug
# -------------------------------------------------
def debug(msg):
    print(f"[PY-DEBUG {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# -------------------------------------------------
# Run bash script natively on Ubuntu
# -------------------------------------------------
def run_script_native(script_contents, output_file):
    script_dir = os.path.join("pipeline_runs", "scripts")
    os.makedirs(script_dir, exist_ok=True)

    script_path = os.path.join(script_dir, f"{uuid.uuid4()}.sh")
    with open(script_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(script_contents)

    os.chmod(script_path, 0o755)

    # Start process
    process = subprocess.Popen(
        ["conda", "run", "-n", "pipeline", "bash", script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,         
    )

    # Stream logs in real time
    with open(output_file, "w", encoding="utf-8") as logf:
        for line in process.stdout:
            logf.write(line)
            logf.flush()

    ret = process.wait()
    if ret != 0:
        raise RuntimeError(f"Pipeline aborted with exit code {ret}")

    

# -------------------------------------------------
# MAIN PIPELINE ENTRY (Native Ubuntu)
# -------------------------------------------------
def run_pipeline_async(
    input_fastq,
    output_dir,
    genome_size,
    threads,
    output_file,
    min_length,
    keep_percent,
    blast_db_path=""
):
    debug("Launching pipeline")

    input_fastq = os.path.abspath(input_fastq)
    output_dir = os.path.abspath(output_dir)
    blast_db_path = os.path.abspath(blast_db_path) if blast_db_path else ""

    script = f"""#!/usr/bin/env bash
set -euo pipefail

# -------------------------------------------------
# PARAMETERS
# -------------------------------------------------
INPUT_FASTQ="{input_fastq}"
OUTPUT_DIR="{output_dir}"
GENOME_SIZE="{genome_size}"
THREADS="{threads}"
MIN_LENGTH="{min_length}"
KEEP_PERCENT="{keep_percent}"
BLAST_DB_PATH="{blast_db_path}"

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
    bash -c "$CMD" &
    PID=$!

    while kill -0 "$PID" 2>/dev/null; do
        if [ -f "$OUTPUT_DIR/CANCEL" ]; then
            log "CANCEL REQUESTED — stopping PID $PID"
            kill -TERM "$PID" 2>/dev/null || true
            sleep 2
            kill -KILL "$PID" 2>/dev/null || true
            log "PIPELINE CANCELLED BY USER"
            touch "$OUTPUT_DIR/PIPELINE_ABORTED"
            exit 0
        fi
        sleep 1
    done

    wait "$PID"
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

# -------------------------------------------------
# STEP 1: Porechop
# -------------------------------------------------
log "STEP 1: Porechop"
if command -v porechop &>/dev/null; then
    mkdir -p "$OUTPUT_DIR/porechop"
    run_with_cancel "porechop -i '$INPUT_FASTQ' -o '$OUTPUT_DIR/porechop/trimmed.fastq'"
else
    log "Porechop skipped"
fi

# -------------------------------------------------
# STEP 2: Deduplication
# -------------------------------------------------
log "STEP 2: Deduplicating reads"
if command -v seqkit &>/dev/null && [ -f "$OUTPUT_DIR/porechop/trimmed.fastq" ]; then
    mkdir -p "$OUTPUT_DIR/dedup"
    run_with_cancel "seqkit rename \
        '$OUTPUT_DIR/porechop/trimmed.fastq' \
        -o '$OUTPUT_DIR/dedup/dedup.fastq'"
else
    log "Deduplication skipped"
fi

# -------------------------------------------------
# STEP 3: Filtlong
# -------------------------------------------------
log "STEP 3: Filtlong"
if command -v filtlong &>/dev/null && [ -f "$OUTPUT_DIR/dedup/dedup.fastq" ]; then
    mkdir -p "$OUTPUT_DIR/filtlong"
    run_with_cancel "filtlong --min_length '$MIN_LENGTH' --keep_percent '$KEEP_PERCENT' \
        '$OUTPUT_DIR/dedup/dedup.fastq' > '$OUTPUT_DIR/filtlong/filtered.fastq'"
else
    log "Filtlong skipped"
fi

# -------------------------------------------------
# STEP 4: Flye
# -------------------------------------------------
log "STEP 4: Flye"
if command -v flye &>/dev/null && [ -f "$OUTPUT_DIR/filtlong/filtered.fastq" ]; then
    mkdir -p "$OUTPUT_DIR/flye"
    run_with_cancel "flye --nano-raw '$OUTPUT_DIR/filtlong/filtered.fastq' \
        --out-dir '$OUTPUT_DIR/flye' \
        --threads '$THREADS' \
        --genome-size '$GENOME_SIZE'"
else
    log "Flye skipped"
fi

# -------------------------------------------------
# STEP 5: Minimap2
# -------------------------------------------------
log "STEP 5: Minimap2"
if command -v minimap2 &>/dev/null && [ -f "$OUTPUT_DIR/flye/assembly.fasta" ]; then
    mkdir -p "$OUTPUT_DIR/racon"
    run_with_cancel "minimap2 -t '$THREADS' -x map-ont \
        '$OUTPUT_DIR/flye/assembly.fasta' \
        '$OUTPUT_DIR/filtlong/filtered.fastq' > '$OUTPUT_DIR/racon/reads.paf'"
else
    log "Minimap2 skipped"
fi

# -------------------------------------------------
# STEP 6: Racon
# -------------------------------------------------
log "STEP 6: Racon"
if command -v racon &>/dev/null && [ -f "$OUTPUT_DIR/racon/reads.paf" ]; then
    run_with_cancel "racon -t '$THREADS' \
        '$OUTPUT_DIR/filtlong/filtered.fastq' \
        '$OUTPUT_DIR/racon/reads.paf' \
        '$OUTPUT_DIR/flye/assembly.fasta' > '$OUTPUT_DIR/racon/polished.fasta'"
else
    log "Racon skipped"
fi

# -------------------------------------------------
# STEP 7: FastQC
# -------------------------------------------------
log "STEP 7: FastQC"
if command -v fastqc &>/dev/null; then
    mkdir -p "$OUTPUT_DIR/fastqc/raw" "$OUTPUT_DIR/fastqc/filtered"
    run_with_cancel "fastqc '$INPUT_FASTQ' -o '$OUTPUT_DIR/fastqc/raw'"

    if [ -f "$OUTPUT_DIR/filtlong/filtered.fastq" ]; then
        run_with_cancel "fastqc '$OUTPUT_DIR/filtlong/filtered.fastq' -o '$OUTPUT_DIR/fastqc/filtered'"
    fi
else
    log "FastQC skipped"
fi

# -------------------------------------------------
# STEP 8: Prokka
# -------------------------------------------------
log "STEP 8: Prokka"
if command -v prokka &>/dev/null && [ -f "$OUTPUT_DIR/racon/polished.fasta" ]; then
    mkdir -p "$OUTPUT_DIR/prokka"
    run_with_cancel "prokka --outdir '$OUTPUT_DIR/prokka' \
        --force \
        --prefix genome '$OUTPUT_DIR/racon/polished.fasta'"
else
    log "Prokka skipped"
fi

# -------------------------------------------------
# STEP 9: QUAST
# -------------------------------------------------
log "STEP 9: QUAST"
if command -v quast &>/dev/null && [ -f "$OUTPUT_DIR/racon/polished.fasta" ]; then
    mkdir -p "$OUTPUT_DIR/quast"
    run_with_cancel "quast '$OUTPUT_DIR/racon/polished.fasta' -o '$OUTPUT_DIR/quast'"
else
    log "QUAST skipped"
fi

log "PIPELINE FINISHED"
"""

    run_script_native(script, output_file)
