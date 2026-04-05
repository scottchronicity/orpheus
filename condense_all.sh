#!/usr/bin/env bash

# Stop the script if any command fails
set -e

# 1) Run the three condensers
./condense_for_llm.monorepo.Makefile.sh
./condense_for_llm.monorepo.sh
./condense_for_llm.monorepo.markdown.sh

# 2) Concatenate their outputs into one file
cat \
  orpheus-condensed-for-llm-Makefile.out \
  orpheus-condensed-for-llm.out \
  orpheus-condensed-for-llm-markdown.md \
  > orpheus-condensed-for-llm.all.out

echo "✨ Done: wrote orpheus-condensed-for-llm.all.out"
