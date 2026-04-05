#!/bin/bash
# condenses the orpheus-gps service files into a single output file for LLM ingestion


SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT/services/orpheus-gps"

OUTPUT_FILE="orpheus-gps-condensed-for-llm.out"

# Initialize/Clear the output file
> "$OUTPUT_FILE"

echo "Generating $OUTPUT_FILE..."

# Function to append file content with delimiter
append_file() {
    local filepath="$1"
    # Output format: <relative/path/to/file>
    # We will use the relative path found by find (e.g., ./src/module/main.py)
    
    echo "<$filepath>" >> "$OUTPUT_FILE"
    cat "$filepath" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
}

# Find Python files
# Exclude __pycache__, __init__.py, tests, venv, and build artifacts
find . -type f -name "*.py" \
    -not -path "*/__pycache__/*" \
    -not -path "*/venv/*" \
    -not -path "*/.venv/*" \
    -not -path "*/env/*" \
    -not -path "*/ENV/*" \
    -not -path "*/build/*" \
    -not -path "*/dist/*" \
    -not -path "*/.pytest_cache/*" \
    -not -path "*/.ruff_cache/*" \
    -not -path "*/.mypy_cache/*" \
    -not -path "*/htmlcov/*" \
    -not -path "*/*.egg-info/*" \
    -not -path "*/.*" \
    -not -name "__init__.py" \
    -not -path "./tests/*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find Shell scripts (excluding this one and output files)
find . -type f -name "*.sh" \
    -not -name "condense_for_llm*.sh" \
    -not -path "*/venv/*" \
    -not -path "*/.venv/*" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find systemd service files
find . -type f -name "*.service" \
    -not -path "*/venv/*" \
    -not -path "*/.venv/*" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Include Makefile, requirements.txt, and README as they are high value for LLMs
if [ -f "Makefile" ]; then
    append_file "./Makefile"
fi
if [ -f "requirements.txt" ]; then
    append_file "./requirements.txt"
fi
if [ -f "README.md" ]; then
    append_file "./README.md"
fi

echo "Done! Content written to $OUTPUT_FILE"
