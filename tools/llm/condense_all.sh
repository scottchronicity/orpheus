#!/usr/bin/env bash
# Run from the repo root: ./tools/llm/condense_all.sh

# Stop the script if any command fails
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# 1) Run the three condensers
"$SCRIPT_DIR/condense_for_llm.monorepo.Makefile.sh"
"$SCRIPT_DIR/condense_for_llm.monorepo.sh"
"$SCRIPT_DIR/condense_for_llm.monorepo.markdown.sh"

# 2) Concatenate their outputs into one file
cat \
  orpheus-condensed-for-llm-Makefile.out \
  orpheus-condensed-for-llm.out \
  orpheus-condensed-for-llm-markdown.md \
  > orpheus-condensed-for-llm.all.out

echo "✨ Done: wrote orpheus-condensed-for-llm.all.out"
