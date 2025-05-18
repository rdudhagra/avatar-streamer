#!/bin/bash

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Check if conda is installed and in PATH
if ! command -v conda &> /dev/null; then
    echo "Error: conda is not installed or not in PATH"
    exit 1
fi

# Check if the environment exists
if ! conda env list | grep -q "avatar-streamer"; then
    echo "Creating conda environment 'avatar-streamer'..."
    conda env create -f "$ROOT_DIR/environment.yml"
fi

# Activate the conda environment and run the Python script
echo "Starting robot stream..."
conda run -n avatar-streamer --no-capture-output python "$SCRIPT_DIR/stream.py" --config "$ROOT_DIR/params.yaml"