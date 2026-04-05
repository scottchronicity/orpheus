#!/usr/bin/env python3
"""
Migration script to rename old-format timelapse files to new format.

Old format: {HH-MM}.{camera_name}.mp4 (e.g., 23-00.orpheus-eye-1.mp4)
New format: {camera_id}.{label}.{tier}.{lookback}.{YYYYMMDD-HHMMSS}.mp4
            (e.g., orpheus-eye-1.daily.tl0.24h.20260124-230000.mp4)

Usage:
    python migrate_timelapse_names.py /data/orpheus/video/timelapses --dry-run
    python migrate_timelapse_names.py /data/orpheus/video/timelapses

The script will:
1. Scan all date directories in the timelapse folder
2. Find files matching the old naming pattern
3. Rename them to the new format

With --dry-run, it only prints what it would do without making changes.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# Tier mapping based on common lookback windows
# Since old format doesn't include lookback info, we infer from the start_time
TIME_TO_TIER = {
    "23:00": ("daily", "tl0", "24h"),  # 11 PM daily timelapse
    "00:00": ("hourly", "tl1", "1h"),  # Midnight/hourly timelapse
}

# Default tier if we can't infer from time
DEFAULT_TIER = ("timelapse", "tlX", "unknown")


def parse_old_filename(filename: str) -> dict | None:
    """
    Parse old format filename: HH-MM.camera_name.mp4

    Returns dict with camera_name, hour, minute or None if not matching.
    """
    pattern = r"^(\d{2})-(\d{2})\.(.+)\.mp4$"
    match = re.match(pattern, filename)
    if not match:
        return None

    return {
        "hour": match.group(1),
        "minute": match.group(2),
        "camera_name": match.group(3),
    }


def generate_new_filename(old_info: dict, date_str: str, mtime: float) -> str:
    """
    Generate new format filename from old format info.

    Args:
        old_info: Parsed old filename info
        date_str: Date in YYYY.MM.DD format (from directory name)
        mtime: File modification time (Unix timestamp)

    Returns:
        New filename in format: camera.label.tier.lookback.timestamp.mp4
    """
    camera_name = old_info["camera_name"]
    hour = old_info["hour"]
    minute = old_info["minute"]

    # Try to infer tier from start time
    start_time = f"{hour}:{minute}"
    label, tier, lookback = TIME_TO_TIER.get(start_time, DEFAULT_TIER)

    # Use modification time for the timestamp
    # Convert to datetime and format
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    timestamp_str = dt.strftime("%Y%m%d-%H%M%S")

    return f"{camera_name}.{label}.{tier}.{lookback}.{timestamp_str}.mp4"


def migrate_directory(timelapse_base: Path, dry_run: bool = True) -> int:
    """
    Migrate all old-format files in the timelapse directory.

    Args:
        timelapse_base: Path to timelapse base directory (e.g., /data/orpheus/video/timelapses)
        dry_run: If True, only print what would be done

    Returns:
        Number of files migrated (or would be migrated)
    """
    if not timelapse_base.exists():
        print(f"Error: Directory does not exist: {timelapse_base}")
        return 0

    migrated_count = 0
    error_count = 0

    # Iterate through date directories
    for date_dir in sorted(timelapse_base.iterdir()):
        if not date_dir.is_dir():
            continue

        # Validate date format YYYY.MM.DD
        date_str = date_dir.name
        if not re.match(r"^\d{4}\.\d{2}\.\d{2}$", date_str):
            print(f"Skipping non-date directory: {date_dir.name}")
            continue

        # Find old-format files in this directory
        for mp4_file in date_dir.glob("*.mp4"):
            old_info = parse_old_filename(mp4_file.name)
            if not old_info:
                # Not an old-format file, skip
                continue

            try:
                mtime = mp4_file.stat().st_mtime
                new_filename = generate_new_filename(old_info, date_str, mtime)
                new_path = date_dir / new_filename

                if new_path.exists():
                    print(f"Warning: Target already exists, skipping: {new_path}")
                    continue

                if dry_run:
                    print(f"Would rename: {mp4_file.name}")
                    print(f"         to: {new_filename}")
                else:
                    mp4_file.rename(new_path)
                    print(f"Renamed: {mp4_file.name} -> {new_filename}")

                migrated_count += 1

            except Exception as e:
                print(f"Error processing {mp4_file}: {e}")
                error_count += 1

    print()
    if dry_run:
        print(f"Dry run complete. Would migrate {migrated_count} files.")
    else:
        print(f"Migration complete. Migrated {migrated_count} files.")

    if error_count > 0:
        print(f"Errors encountered: {error_count}")

    return migrated_count


def main():
    parser = argparse.ArgumentParser(
        description="Migrate old-format timelapse filenames to new format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "timelapse_dir",
        type=Path,
        help="Path to timelapse directory (e.g., /data/orpheus/video/timelapses)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )

    args = parser.parse_args()

    print(f"Timelapse directory: {args.timelapse_dir}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    if not args.dry_run:
        confirm = input("This will rename files. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            return 1

    migrate_directory(args.timelapse_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
