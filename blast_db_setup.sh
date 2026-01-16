#!/bin/bash

# ==========================================
#       BLAST Database Setup
# ==========================================

clear
echo "=========================================="
echo "      BLAST Database Setup"
echo "=========================================="
echo
echo "This utility helps you create a BLAST database from a reference FASTA file."
echo

# ---------- INPUT ----------
while true; do
    read -rp "Enter full path to your reference FASTA file (e.g., /home/user/data/ref.fasta): " FASTA_FILE

    if [[ -f "$FASTA_FILE" ]]; then
        break
    else
        echo "[ERROR] File not found. Please try again."
    fi
done

read -rp "Enter a name for this database (e.g., my_genome_db): " DB_NAME

echo
echo "[INFO] Processing..."
echo "1. Validating environment..."
echo

# ---------- OPTIONAL: Conda ----------
# Comment these lines if you are not using conda
if command -v conda >/dev/null 2>&1; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate pipeline || {
        echo "[ERROR] Failed to activate conda environment 'pipeline'"
        exit 1
    }
fi

# ---------- CHECK makeblastdb ----------
if ! command -v makeblastdb >/dev/null 2>&1; then
    echo "[ERROR] makeblastdb is not installed."
    echo "Install it using:"
    echo "  sudo apt install ncbi-blast+"
    exit 1
fi

echo "2. Running makeblastdb..."
echo

# ---------- RUN makeblastdb ----------
makeblastdb \
    -in "$FASTA_FILE" \
    -dbtype nucl \
    -out "$(dirname "$FASTA_FILE")/$DB_NAME"

if [[ $? -ne 0 ]]; then
    echo
    echo "[ERROR] Failed to create BLAST database."
    exit 1
fi

echo
echo "[SUCCESS] Database created successfully!"
echo "Database files are located at:"
echo "$(dirname "$FASTA_FILE")/${DB_NAME}.*"
echo
