#!/usr/bin/env bash
set -e

ENV_NAME="pipeline"

echo "=========================================="
echo " Bioinformatics Pipeline Installer"
echo "=========================================="

# -----------------------------
# Check Conda
# -----------------------------
if ! command -v conda &> /dev/null; then
    echo "❌ Conda not found."
    echo "Install Miniconda first:"
    echo "https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

echo "✅ Conda detected"

# -----------------------------
# Initialize Conda (non-interactive)
# -----------------------------
source "$(conda info --base)/etc/profile.d/conda.sh"

# -----------------------------
# Create Conda environment
# -----------------------------
if conda env list | grep -q "^$ENV_NAME "; then
    echo "⚠️ Conda environment '$ENV_NAME' already exists"
else
    echo "📦 Creating Conda environment: $ENV_NAME"
    conda env create -f environment.yml
fi

# -----------------------------
# Activate environment
# -----------------------------
echo "🔁 Activating environment"
conda activate $ENV_NAME

# -----------------------------
# Install pip dependencies
# -----------------------------
if [ -f "requirements.txt" ]; then
    echo "📦 Installing Python dependencies"
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt not found – skipping pip install"
fi

# -----------------------------
# Verify key tools
# -----------------------------
echo "🔍 Verifying installations"

TOOLS=(
  flye
  porechop
  filtlong
  minimap2
  racon
  fastqc
  quast
  blastn
  prokka
)

for tool in "${TOOLS[@]}"; do
    if command -v "$tool" &> /dev/null; then
        echo "✅ $tool installed"
    else
        echo "❌ $tool NOT found"
        exit 1
    fi
done

echo "=========================================="
echo " ✅ Installation completed successfully"
echo " Activate with: conda activate $ENV_NAME"
echo "=========================================="
