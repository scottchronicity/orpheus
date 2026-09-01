#!/usr/bin/env bash
# bump-version.sh — bump one component's VERSION (SemVer) and stub its CHANGELOG.
#
# Usage: scripts/bump-version.sh <component-path> <major|minor|patch>
#   e.g. scripts/bump-version.sh platform/orpheus-common minor
#        scripts/bump-version.sh agents/orpheus-agent-bird-detection patch
#
# The VERSION file is each component's single source of truth — setuptools
# reads it at build time via [tool.setuptools.dynamic]. See docs/adr/0014.
# Works with the macOS-bundled bash 3.2 (no associative arrays, no mapfile).
set -euo pipefail

usage() {
  echo "Usage: $0 <component-path> <major|minor|patch>" >&2
  exit 2
}

[ $# -eq 2 ] || usage
component="$1"
part="$2"

case "$part" in
  major | minor | patch) ;;
  *)
    echo "error: bump part must be major, minor, or patch (got '$part')" >&2
    usage
    ;;
esac

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
version_file="$repo_root/$component/VERSION"

if [ ! -f "$version_file" ]; then
  echo "error: no VERSION file at $version_file" >&2
  echo "       (is '$component' a real component path with a VERSION file?)" >&2
  exit 1
fi

current="$(tr -d '[:space:]' < "$version_file")"
if ! printf '%s' "$current" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "error: VERSION '$current' in $version_file is not strict SemVer X.Y.Z" >&2
  exit 1
fi

major="${current%%.*}"
rest="${current#*.}"
minor="${rest%%.*}"
patch="${rest#*.}"

case "$part" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac
new="$major.$minor.$patch"

printf '%s\n' "$new" > "$version_file"

# Prepend a dated stub to the component's CHANGELOG (create it if missing).
# Edit the stub before committing — this only scaffolds the entry.
changelog="$repo_root/$component/CHANGELOG.md"
today="$(date +%Y-%m-%d)"
tmp="$(mktemp)"
if [ -f "$changelog" ]; then
  header="$(head -n 1 "$changelog")"
  body="$(tail -n +2 "$changelog")"
  {
    printf '%s\n\n' "$header"
    printf '## %s — %s\n\n- _Describe the change here._\n\n' "$new" "$today"
    printf '%s\n' "$body"
  } > "$tmp"
else
  printf '# Changelog\n\n## %s — %s\n\n- _Describe the change here._\n' "$new" "$today" > "$tmp"
fi
mv "$tmp" "$changelog"

echo "Bumped $component: $current -> $new ($part)"
echo "  VERSION:   $version_file"
echo "  CHANGELOG: $changelog (stub prepended — edit it before committing)"
echo
echo "Remember: if this is orpheus-common and the bump is a BREAKING (major)"
echo "change, raise the 'orpheus-common>=' floor in dependents' pyproject.toml"
echo "and update docs/version-compat-matrix.md."
