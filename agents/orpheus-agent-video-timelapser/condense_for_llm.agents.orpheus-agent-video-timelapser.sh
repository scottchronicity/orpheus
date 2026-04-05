#!/bin/bash
# Condense the orpheus-agent-video-timelapser agent into a single file for LLM ingestion

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

OUTPUT_FILE="orpheus-agent-video-timelapser-condensed-for-llm.out"

# Initialize/Clear the output file
> "$OUTPUT_FILE"

echo "Generating $OUTPUT_FILE..."

# Add tree structure at the top for context
echo "<FULL TREE>" >> "$OUTPUT_FILE"
if command -v tree &> /dev/null; then
	tree -I '__pycache__|*.pyc|.git|.idea|.mypy_cache|*.egg-info|venv|build|dist|*.out' >> "$OUTPUT_FILE"
else
	find . -type f -o -type d | \
		grep -v -E '__pycache__|\.pyc$|\.git|\.idea|\.mypy_cache|\.egg-info|venv|build|dist|\.out$' | \
		sort >> "$OUTPUT_FILE"
fi
echo "" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Function to append file content with delimiter
append_file() {
	local filepath="$1"
	echo "<$filepath>" >> "$OUTPUT_FILE"
	cat "$filepath" >> "$OUTPUT_FILE"
	echo "" >> "$OUTPUT_FILE"
	echo "" >> "$OUTPUT_FILE"
}

# Common exclusions for find operations
FIND_EXCLUDES=(
	-not -path "*/__pycache__/*"
	-not -path "*/.git/*"
	-not -path "*/.idea/*"
	-not -path "*/.mypy_cache/*"
	-not -path "*/.*egg-info/*"
	-not -path "*/venv/*"
	-not -path "*/build/*"
	-not -path "*/dist/*"
)

# Collect project files of interest and append them in sorted order
find . -type f \
	\( -name "*.py" -o -name "*.md" -o -name "*.sh" -o -name "*.txt" -o -name "*.toml" -o -name "*.yaml" -o -name "Makefile" \) \
	-not -name "*.pyc" \
	-not -name "condense_for_llm*" \
	-not -name "*condensed*" \
	"${FIND_EXCLUDES[@]}" \
	-print0 | sort -z | while IFS= read -r -d '' file; do
	append_file "$file"
done

# Include top-level .env if present
if [ -f "./.env" ]; then
	append_file "./.env"
fi

echo "Done! Content written to $OUTPUT_FILE"
