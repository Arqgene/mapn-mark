#!/bin/bash
set -e

echo "Starting Setup..."

# -----------------------------------------
# Run installer
# -----------------------------------------
chmod +x install.sh
./install.sh

# -----------------------------------------
# Activate Conda environment
# -----------------------------------------
eval "$(conda shell.bash hook)"
conda activate pipeline

# -----------------------------------------
# Dynamically patch QUAST shebang
# -----------------------------------------
if command -v quast &>/dev/null; then
    QUAST_PATH="$(which quast)"
    CONDA_PYTHON="$(which python)"

    echo "Patching QUAST shebang..."
    echo "  QUAST  : $QUAST_PATH"
    echo "  PYTHON : $CONDA_PYTHON"

    sed -i "1s|^#!.*python.*|#!$CONDA_PYTHON|" "$QUAST_PATH"
else
    echo "WARNING: quast not found, skipping patch"
fi

# -----------------------------------------
# Database setup
# -----------------------------------------
echo "Do you want to create database? (yes/no)"
read choice

if [[ "$choice" == "yes" || "$choice" == "y" ]]; then
    echo "Creating database user for gene_app..."

    sudo mysql <<EOF
CREATE DATABASE IF NOT EXISTS gene_app;
CREATE USER IF NOT EXISTS 'arqgene_user'@'localhost' IDENTIFIED BY 'arqgene@2026';
GRANT ALL PRIVILEGES ON gene_app.* TO 'arqgene_user'@'localhost';
FLUSH PRIVILEGES;
EOF

    echo "Initializing Database..."
    python create_user.py
else
    echo "Database creation skipped."
fi

# -----------------------------------------
# BLAST DB setup
# -----------------------------------------
echo "Do you want to create BLAST DB? (yes/no)"
read choice

if [[ "$choice" == "yes" || "$choice" == "y" ]]; then
    echo "Creating BLAST database..."
    chmod +x blast_db_setup.sh
    ./blast_db_setup.sh
else
    echo "BLAST database creation skipped."
fi

echo "Setup Complete!"
