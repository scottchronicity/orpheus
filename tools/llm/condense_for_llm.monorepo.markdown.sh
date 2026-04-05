#!/bin/bash

echo "<FULL TREE>" > orpheus-condensed-for-llm-markdown.md
echo >> orpheus-condensed-for-llm-markdown.md

git ls-files '*.md' | sed 's/^/ - /' >> orpheus-condensed-for-llm-markdown.md

git ls-files '*.md' | while read -r f; do
    echo >> orpheus-condensed-for-llm-markdown.md
    echo "<./$f>" >> orpheus-condensed-for-llm-markdown.md
    echo >> orpheus-condensed-for-llm-markdown.md
    cat "$f" >> orpheus-condensed-for-llm-markdown.md
done
