#!/bin/bash
# condenses the orpheus-backplane project files into a single output file for LLM ingestion


SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT/services/orpheus-backplane"

OUTPUT_FILE="orpheus-backplane-condensed-for-llm.out"

# Initialize/Clear the output file
> "$OUTPUT_FILE"

echo "Generating $OUTPUT_FILE..."

# Function to append file content with delimiter
append_file() {
    local filepath="$1"
    # User requested format: </PATH/TO/FILE1>
    # We will use the relative path found by find (e.g., ./src/module/main.py)
    
    echo "<$filepath>" >> "$OUTPUT_FILE"
    cat "$filepath" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
}

# Find Python files
# Exclude __pycache__, __init__.py, and tests directory
find . -type f -name "*.py" \
    -not -path "*/__pycache__/*" \
    -not -name "__init__.py" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find Configuration files (.conf)
find . -type f -name "*.conf" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find Systemd service files (.service)
find . -type f -name "*.service" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find Markdown files (.md)
find . -type f -name "*.md" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Find Shell scripts (excluding this one)
find . -type f -name "*.sh" \
    -not -name "condense_for_llm.sh" \
    -not -path "*/.*" \
    -print0 | while IFS= read -r -d '' file; do
    append_file "$file"
done

# Include Makefile and requirements.txt as they are high value for LLMs
if [ -f "Makefile" ]; then
    append_file "./Makefile"
fi
if [ -f "requirements.txt" ]; then
    append_file "./requirements.txt"
fi

echo "Done! Content written to $OUTPUT_FILE"
