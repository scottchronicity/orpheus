#!/bin/bash
#
# migrate_timelapse_filenames.sh
#
# Migrates old-format timelapse filenames to new format:
#   Old: HH-MM.camera_name.mp4
#   New: camera_name.label.tier.lookback.YYYYMMDD-HHMMSS.mp4
#
# Usage:
#   ./migrate_timelapse_filenames.sh [--dry-run] [timelapse_dir]
#
# Arguments:
#   --dry-run       Show what would be renamed without actually renaming
#   timelapse_dir   Path to timelapses directory (default: /data/orpheus/video/timelapses)
#
# Example:
#   ./migrate_timelapse_filenames.sh --dry-run
#   ./migrate_timelapse_filenames.sh
#   ./migrate_timelapse_filenames.sh /path/to/custom/timelapses
#

set -euo pipefail

DRY_RUN=false
TIMELAPSE_DIR="/data/orpheus/video/timelapses"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            TIMELAPSE_DIR="$1"
            shift
            ;;
    esac
done

if [[ ! -d "$TIMELAPSE_DIR" ]]; then
    echo "Error: Timelapse directory not found: $TIMELAPSE_DIR"
    exit 1
fi

echo "Timelapse migration script"
echo "=========================="
echo "Directory: $TIMELAPSE_DIR"
echo "Dry run: $DRY_RUN"
echo ""

# Counter for files
total_files=0
migrated_files=0
skipped_files=0
error_files=0

# Find all .mp4 files in the timelapse directory
while IFS= read -r -d '' file; do
    total_files=$((total_files + 1))
    
    filename=$(basename "$file")
    dirpath=$(dirname "$file")
    date_dir=$(basename "$dirpath")
    
    # Check if this is old format: HH-MM.camera_name.mp4
    if [[ "$filename" =~ ^([0-9]{2})-([0-9]{2})\.(.+)\.mp4$ ]]; then
        hour="${BASH_REMATCH[1]}"
        minute="${BASH_REMATCH[2]}"
        camera_name="${BASH_REMATCH[3]}"
        
        # Parse date from directory name (YYYY.MM.DD)
        if [[ "$date_dir" =~ ^([0-9]{4})\.([0-9]{2})\.([0-9]{2})$ ]]; then
            year="${BASH_REMATCH[1]}"
            month="${BASH_REMATCH[2]}"
            day="${BASH_REMATCH[3]}"
            
            # Build new filename
            # Assume 24h daily timelapse for old format (since that was the only format before)
            # Format: camera_name.daily.tl0.24h.YYYYMMDD-HHMMSS.mp4
            new_filename="${camera_name}.daily.tl0.24h.${year}${month}${day}-${hour}${minute}00.mp4"
            new_path="${dirpath}/${new_filename}"
            
            if [[ -f "$new_path" ]]; then
                echo "SKIP: $filename -> $new_filename (target exists)"
                skipped_files=$((skipped_files + 1))
            else
                if [[ "$DRY_RUN" == "true" ]]; then
                    echo "WOULD RENAME: $filename -> $new_filename"
                else
                    mv "$file" "$new_path"
                    echo "RENAMED: $filename -> $new_filename"
                fi
                migrated_files=$((migrated_files + 1))
            fi
        else
            echo "ERROR: Could not parse date from directory: $date_dir for file $filename"
            error_files=$((error_files + 1))
        fi
    # Check if already new format: camera_name.label.tier.lookback.timestamp.mp4
    elif [[ "$filename" =~ ^.+\..+\.tl[0-9]+\.[0-9]+[hms]\.[0-9]{8}-[0-9]{6}\.mp4$ ]]; then
        echo "SKIP: $filename (already new format)"
        skipped_files=$((skipped_files + 1))
    else
        echo "UNKNOWN: $filename (unrecognized format)"
        skipped_files=$((skipped_files + 1))
    fi
done < <(find "$TIMELAPSE_DIR" -type f -name "*.mp4" -print0 | sort -z)

echo ""
echo "Summary:"
echo "  Total files:    $total_files"
echo "  Migrated:       $migrated_files"
echo "  Skipped:        $skipped_files"
echo "  Errors:         $error_files"

if [[ "$DRY_RUN" == "true" && $migrated_files -gt 0 ]]; then
    echo ""
    echo "This was a dry run. Run without --dry-run to actually rename files."
fi
