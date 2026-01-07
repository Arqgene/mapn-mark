#!/bin/bash

# List of tools to check
TOOLS=("porechop" "filtlong" "flye" "minimap2" "racon" "fastqc" "prokka" "quast" "python3")

# Define paths to check
CONDA_PATHS=(
    "$HOME/miniconda3"
    "$HOME/anaconda3"
    "$HOME/miniforge3"
    "/opt/conda"
    "/usr/local/conda"
)

# 1. Try to source conda.sh directly (best for scripts)
sourced_conda=false
for path in "${CONDA_PATHS[@]}"; do
    if [ -f "$path/etc/profile.d/conda.sh" ]; then
        . "$path/etc/profile.d/conda.sh"
        sourced_conda=true
        break
    fi
done

# 2. If not sourced, try to use 'conda shell.bash hook' using conda from PATH
if [ "$sourced_conda" = false ] && command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
fi

# 3. Activate environment
conda activate pipeline 2>/dev/null

echo "{"
echo "  \"tools\": ["

first=true

for tool in "${TOOLS[@]}"; do
    if [ "$first" = true ]; then
        first=false
    else
        echo "    ,"
    fi

    if command -v $tool &> /dev/null; then
        # Capture version, filtering out potential warnings (like locale issues)
        version=$($tool --version 2>&1 | grep -v "WARNING" | head -n 1 | tr -d '"')
        if [ -z "$version" ]; then
             version="Installed"
        fi
        echo "    { \"name\": \"$tool\", \"installed\": true, \"version\": \"$version\" }"
    else
        echo "    { \"name\": \"$tool\", \"installed\": false, \"version\": null }"
    fi
done

echo "  ]"
echo "}"
