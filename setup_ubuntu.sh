#!/bin/bash
set -e

echo "Starting Setup..."

# Ensure install.sh is executable
chmod +x install.sh
./install.sh

# Activate conda
eval "$(conda shell.bash hook)"
conda activate pipeline

echo "Creating database user for gene_app..."

sudo mysql <<EOF
CREATE DATABASE IF NOT EXISTS gene_app;
CREATE USER IF NOT EXISTS 'gene_user'@'localhost' IDENTIFIED BY 'arqgene@2026';
GRANT ALL PRIVILEGES ON gene_app.* TO 'gene_user'@'localhost';
FLUSH PRIVILEGES;
EOF

echo "Initializing Database..."
python create_user.py

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

