#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="pipeline"
EXPECTED_PYTHON_MAJOR=3
EXPECTED_PYTHON_MINOR=10

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
# Initialize Conda
# -----------------------------
source "$(conda info --base)/etc/profile.d/conda.sh"

# -----------------------------
# Ensure Mamba
# -----------------------------
if ! command -v mamba &> /dev/null; then
    echo "📦 Installing mamba into base environment"
    conda activate base
    conda install -y -n base -c conda-forge mamba
fi

# -----------------------------
# Create environment
# -----------------------------
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "⚠️ Conda environment '$ENV_NAME' already exists"
else
    echo "📦 Creating Conda environment: $ENV_NAME"
    mamba env create -f environment.yml
fi

# -----------------------------
# Activate environment
# -----------------------------
echo "🔁 Activating environment"
conda activate "$ENV_NAME"

# -----------------------------
# Validate Python version
# -----------------------------
PY_VERSION=$(python - <<EOF
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
EOF
)

if [[ "$PY_VERSION" != "$EXPECTED_PYTHON_MAJOR.$EXPECTED_PYTHON_MINOR" ]]; then
    echo "❌ ERROR: Python $PY_VERSION detected"
    echo "   Expected Python $EXPECTED_PYTHON_MAJOR.$EXPECTED_PYTHON_MINOR"
    exit 1
fi

echo "✅ Python version OK: $PY_VERSION"



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
