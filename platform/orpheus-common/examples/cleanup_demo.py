#!/usr/bin/env python3
"""
Example script demonstrating storage cleanup usage.

Run with:
    python examples/cleanup_demo.py --help
"""

import argparse
import logging
from pathlib import Path

from orpheus_common.storage.cleanup import CleanupPolicy, StorageCleanup, cleanup_old_files_by_age

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def demo_policy_based_cleanup(path: Path, dry_run: bool = True):
    """Demonstrate policy-based cleanup with different strategies."""
    print("\n" + "=" * 70)
    print("POLICY-BASED CLEANUP DEMO")
    print("=" * 70)

    strategies = ["oldest", "largest", "random"]

    for strategy in strategies:
        print(f"\n--- Strategy: {strategy} ---")

        policy = CleanupPolicy(
            max_size_gb=1.0,  # Small limit for demo
            cleanup_trigger_percent=50.0,  # Trigger at 50%
            cleanup_amount_percent=20.0,  # Remove 20%
            cleanup_strategy=strategy,
            min_file_age_hours=0.0,  # For demo purposes
            file_pattern="*",
        )

        cleanup = StorageCleanup(policy)

        # Check current usage
        used_bytes, used_percent = cleanup.calculate_usage(path)
        print(f"Current usage: {used_bytes / (1024**2):.2f} MB ({used_percent:.1f}%)")

        # Check if cleanup needed
        if cleanup.needs_cleanup(path):
            print(f"✓ Cleanup triggered (>{policy.cleanup_trigger_percent}%)")

            # Perform cleanup
            result = cleanup.cleanup(path, dry_run=dry_run)

            print(f"Files to remove: {result.files_removed}")
            print(f"Space to free: {result.bytes_freed / (1024**2):.2f} MB")
            print(f"Duration: {result.duration_seconds:.2f}s")

            if dry_run:
                print(f"[DRY RUN] Manifest: {result.manifest_path}")
            else:
                print(f"Deleted! Manifest: {result.manifest_path}")
        else:
            print(f"✗ Cleanup not needed (<{policy.cleanup_trigger_percent}%)")


def demo_age_based_cleanup(path: Path, max_age_days: int, dry_run: bool = True):
    """Demonstrate simple age-based cleanup."""
    print("\n" + "=" * 70)
    print(f"AGE-BASED CLEANUP DEMO (>{max_age_days} days)")
    print("=" * 70)

    deleted = cleanup_old_files_by_age(
        path=path, max_age_days=max_age_days, dry_run=dry_run, pattern="*"
    )

    print(f"Files deleted: {deleted}")
    if dry_run:
        print("[DRY RUN] No files actually deleted")


def demo_usage_check(path: Path):
    """Demonstrate usage checking without cleanup."""
    print("\n" + "=" * 70)
    print("STORAGE USAGE CHECK")
    print("=" * 70)

    # Create a policy just for checking usage
    policy = CleanupPolicy(max_size_gb=50.0)
    cleanup = StorageCleanup(policy)

    # Scan directory
    files = cleanup.scan_directory(path)
    print(f"Total files: {len(files)}")

    total_bytes = sum(f.size_bytes for f in files)
    print(f"Total size: {total_bytes / (1024**2):.2f} MB ({total_bytes / (1024**3):.2f} GB)")

    # Calculate usage against limit
    used_bytes, used_percent = cleanup.calculate_usage(path)
    print(f"Usage vs limit: {used_percent:.1f}% of {policy.max_size_gb} GB")

    # Show oldest and newest files
    if files:
        files_by_age = sorted(files, key=lambda f: f.mtime)
        print(f"\nOldest file: {files_by_age[0].path.name} ({files_by_age[0].age_hours:.1f}h)")
        print(f"Newest file: {files_by_age[-1].path.name} ({files_by_age[-1].age_hours:.1f}h)")

        # Show largest files
        files_by_size = sorted(files, key=lambda f: f.size_bytes, reverse=True)[:5]
        print("\nTop 5 largest files:")
        for f in files_by_size:
            print(f"  {f.size_bytes / (1024**2):6.2f} MB - {f.path.name}")


def main():
    parser = argparse.ArgumentParser(description="Demonstrate storage cleanup functionality")
    parser.add_argument("path", type=Path, help="Directory to analyze/clean")
    parser.add_argument(
        "--mode",
        choices=["check", "policy", "age", "all"],
        default="check",
        help="Cleanup mode to demonstrate",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't actually delete files")
    parser.add_argument(
        "--max-age-days", type=int, default=90, help="Maximum age for age-based cleanup"
    )

    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: Path does not exist: {args.path}")
        return 1

    if not args.path.is_dir():
        print(f"Error: Path is not a directory: {args.path}")
        return 1

    print(f"\nAnalyzing directory: {args.path}")
    print(f"Dry run: {args.dry_run}")

    if args.mode in ("check", "all"):
        demo_usage_check(args.path)

    if args.mode in ("policy", "all"):
        demo_policy_based_cleanup(args.path, dry_run=args.dry_run)

    if args.mode in ("age", "all"):
        demo_age_based_cleanup(args.path, args.max_age_days, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    exit(main())
