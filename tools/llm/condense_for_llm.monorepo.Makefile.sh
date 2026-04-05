#!/bin/bash

output="orpheus-condensed-for-llm-Makefile.out"

echo "<FULL TREE>" > "$output"
echo >> "$output"

# List all tracked Makefiles recursively, respecting .gitignore
git ls-files '**/Makefile' | sed 's/^/ - /' >> "$output"

# Append contents
git ls-files '**/Makefile' | while read -r f; do
    echo >> "$output"
    echo "<./$f>" >> "$output"
    echo >> "$output"
    cat "$f" >> "$output"
done