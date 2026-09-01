#!/bin/bash
# Generates a consolidated view of the repository for LLM ingestion.
# Run from the repo root: ./tools/llm/condense_for_llm.monorepo.sh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

"$SCRIPT_DIR/condense_for_llm.platform.orpheus-common.sh"
"$SCRIPT_DIR/condense_for_llm.services.orpheus-backplane.sh"
"$SCRIPT_DIR/condense_for_llm.services.orpheus-bluetooth-autoconnect.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-audio-motion.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-audio-events.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-audio-playback.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-bird-detection.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-crow-detection.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-video-motion.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-video-snapshotter.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-video-timelapser.sh"
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-event-correlator.sh"
"$SCRIPT_DIR/condense_for_llm.services.orpheus-ui.sh"

OUTPUT_FILE="orpheus-condensed-for-llm.out"

# Initialize/Clear the output file
> "$OUTPUT_FILE"

echo "Generating $OUTPUT_FILE..."

echo "<FULL TREE>" >> "$OUTPUT_FILE"
if command -v python3 >/dev/null 2>&1; then
    python3 <<'PY' >> "$OUTPUT_FILE"
import os

ROOT = "."
SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}

def iter_entries(path):
    entries = []
    with os.scandir(path) as it:
        for entry in it:
            if entry.is_dir(follow_symlinks=False) and entry.name in SKIP_DIRS:
                continue
            entries.append(entry)
    entries.sort(key=lambda entry: (0 if entry.is_dir(follow_symlinks=False) else 1, entry.name.lower()))
    return entries

def walk(path, prefix=""):
    entries = iter_entries(path)
    total = len(entries)
    for index, entry in enumerate(entries):
        connector = "+-- " if index == total - 1 else "|-- "
        print(f"{prefix}{connector}{entry.name}")
        if entry.is_dir(follow_symlinks=False):
            extension = "    " if index == total - 1 else "|   "
            walk(os.path.join(path, entry.name), prefix + extension)

print(".")
walk(ROOT)
PY
else
    # Fallback to a simple find if python3 is unavailable
    find . -mindepth 0 -not -path "*/.git/*" -print >> "$OUTPUT_FILE"
fi

echo "" >> "$OUTPUT_FILE"
echo "<SECTIONS IN THIS FILE>" >> "$OUTPUT_FILE"
find . -type f -iname "*condensed-for-llm.out" -print0 | while IFS= read -r -d '' file; do
    if [[ "$file" == "./$OUTPUT_FILE" ]]; then
        continue
    fi
    dir_path="$(dirname "$file")"
    file_count=$(grep -c "^<\." "$file" 2>/dev/null || echo "0")
    echo "- $dir_path ($file_count files)" >> "$OUTPUT_FILE"
done
echo "" >> "$OUTPUT_FILE"

find . -type f -iname "*condensed-for-llm.out" -print0 | sort -z | while IFS= read -r -d '' file; do
    if [[ "$file" == "./$OUTPUT_FILE" ]]; then
        continue
    fi
    dir_path="$(dirname "$file")"
    file_count=$(grep -c "^<\." "$file" || echo "0")
    {
        echo ""
        echo "=========================================="
        echo ">>condensed output from directory $dir_path"
        echo ">>contains $file_count files"
        echo "=========================================="
        cat "$file"
        echo ""
        echo "=========================================="
        echo ">>end of $dir_path"
        echo "=========================================="
        echo ""
    } >> "$OUTPUT_FILE"
done

echo "Done! Content written to $OUTPUT_FILE"
