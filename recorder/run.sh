#!/bin/bash

# Change to the script's directory
cd "$(dirname "$0")"

# Default config path
CONFIG_PATH="../params.yaml"

# Default output directory (will use default in recorder.py if not specified)
OUTPUT_DIR=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --config=*)
      CONFIG_PATH="${1#*=}"
      shift
      ;;
    --output-dir=*)
      OUTPUT_DIR="--output-dir=${1#*=}"
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--config=PATH] [--output-dir=PATH]"
      echo ""
      echo "Options:"
      echo "  --config=PATH       Path to configuration file (default: ../params.yaml)"
      echo "  --output-dir=PATH   Directory to save recordings (default: ./recordings/)"
      echo "  --help, -h          Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Run the recorder script
python3 ./recorder.py --config "$CONFIG_PATH" $OUTPUT_DIR 