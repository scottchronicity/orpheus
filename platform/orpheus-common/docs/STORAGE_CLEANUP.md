# Storage Cleanup Integration Guide

This guide shows how to integrate automatic storage cleanup into Orpheus agents.

## Quick Start

The simplest way to add cleanup to an agent is to use the periodic cleanup task pattern:

```python
import asyncio
import contextlib
from datetime import datetime
from pathlib import Path
from orpheus_common.storage.cleanup import CleanupPolicy, StorageCleanup

class MyAgent:
    def __init__(self, config):
        self._config = config
        self._cleanup_task = None
        self._last_cleanup_time = None
        self._stop_event = asyncio.Event()
    
    async def start(self):
        """Start the agent and background tasks."""
        # Start periodic cleanup
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        # Wait for shutdown
        await self._stop_event.wait()
        await self.stop()
    
    async def stop(self):
        """Stop the agent gracefully."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
    
    async def _periodic_cleanup(self):
        """Periodically check and cleanup storage if needed."""
        check_interval_seconds = self._config.storage.retention.check_interval_hours * 3600
        
        logger.info(f"Storage cleanup task started (check every {check_interval_seconds/3600:.1f} hours)")
        
        while True:
            try:
                await asyncio.sleep(check_interval_seconds)
                
                # Create cleanup policy from config
                policy = CleanupPolicy(
                    max_size_gb=self._config.storage.retention.max_size_gb,
                    max_age_days=self._config.storage.retention.raw_audio_days,
                    cleanup_strategy=self._config.storage.retention.cleanup_strategy,
                    cleanup_trigger_percent=self._config.storage.retention.cleanup_trigger_percent,
                    cleanup_amount_percent=self._config.storage.retention.cleanup_amount_percent,
                    min_file_age_hours=self._config.storage.retention.min_file_age_hours,
                    file_pattern="*.flac",  # Adjust based on your agent
                )
                
                # Get storage path (adjust based on your agent)
                from orpheus_common.storage import get_audio_path
                storage_path = get_audio_path(category="clips")
                
                # Perform cleanup
                logger.info(f"Running storage cleanup check on {storage_path}")
                cleanup = StorageCleanup(policy)
                result = cleanup.cleanup(storage_path, dry_run=False)
                
                if result.files_removed > 0:
                    logger.info(
                        f"Cleanup completed: {result.files_removed} files removed, "
                        f"{result.bytes_freed / (1024**2):.2f} MB freed"
                    )
                    if result.manifest_path:
                        logger.info(f"Deletion manifest: {result.manifest_path}")
                else:
                    logger.debug("No cleanup needed")
                
                self._last_cleanup_time = datetime.now()
            
            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error during periodic cleanup: {e}", exc_info=True)
                # Continue running despite errors
```

## Manual Cleanup

For one-time cleanup operations:

```python
from pathlib import Path
from orpheus_common.storage.cleanup import CleanupPolicy, StorageCleanup

# Create policy
policy = CleanupPolicy(
    max_size_gb=50.0,
    cleanup_trigger_percent=90.0,
    cleanup_amount_percent=25.0,
    cleanup_strategy="oldest",
    min_file_age_hours=1.0,
    file_pattern="*.flac"
)

# Perform cleanup
cleanup = StorageCleanup(policy)
result = cleanup.cleanup(
    path=Path("/data/orpheus/audio/clips"),
    dry_run=False  # Set to True to preview
)

print(f"Removed {result.files_removed} files")
print(f"Freed {result.bytes_freed / (1024**2):.2f} MB")
print(f"Manifest: {result.manifest_path}")
```

## Simple Age-Based Cleanup

For the simple case of removing files older than a certain age:

```python
from pathlib import Path
from orpheus_common.storage.cleanup import cleanup_old_files_by_age

# Remove all files older than 90 days
deleted = cleanup_old_files_by_age(
    path=Path("/data/orpheus/audio/clips"),
    max_age_days=90,
    dry_run=False,
    pattern="*.flac"
)

print(f"Deleted {deleted} old files")
```

## Cleanup Strategies

### Oldest First (Recommended)
```python
policy = CleanupPolicy(cleanup_strategy="oldest")
```
Removes the oldest files by modification time. Best for time-series data like audio clips.

### Largest First
```python
policy = CleanupPolicy(cleanup_strategy="largest")
```
Removes the largest files first. Maximizes space freed per file.

### Random
```python
policy = CleanupPolicy(cleanup_strategy="random")
```
Random selection. Useful for creating unbiased reduced datasets.

## Configuration

Add to your `orpheus.yaml`:

```yaml
storage:
  base_path: "/data/orpheus"
  retention:
    raw_audio_days: 30
    raw_video_days: 30
    detections_days: 365
    # Cleanup settings
    max_size_gb: 50.0                    # Storage limit
    cleanup_trigger_percent: 90.0        # Trigger at 90% full
    cleanup_amount_percent: 25.0         # Remove 25% when triggered
    cleanup_strategy: "oldest"           # Strategy to use
    check_interval_hours: 6.0            # Check every 6 hours
    min_file_age_hours: 1.0              # Never delete files < 1 hour old
```

## Safety Features

1. **Minimum File Age**: Files younger than `min_file_age_hours` are never deleted
2. **Deletion Manifests**: CSV log of all deleted files created before deletion
3. **Dry Run Mode**: Preview what would be deleted without actually deleting
4. **Error Handling**: Continues on individual file errors, logs everything

## Testing

Always test with dry_run first:

```python
# Preview what would be deleted
result = cleanup.cleanup(path, dry_run=True)
print(f"Would delete {result.files_removed} files")

# Check the manifest
import csv
with open(result.manifest_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        print(f"Would delete: {row['path']} ({row['size_bytes']} bytes)")
```

## Monitoring

Check cleanup status:

```python
# Check current usage
used_bytes, used_percent = cleanup.calculate_usage(path)
print(f"Storage: {used_bytes / (1024**3):.2f} GB ({used_percent:.1f}%)")

# Check if cleanup is needed
if cleanup.needs_cleanup(path):
    print("Cleanup needed!")
else:
    print("Storage OK")
```

## Error Handling

Cleanup operations are resilient:

```python
result = cleanup.cleanup(path, dry_run=False)

if result.errors:
    print(f"Encountered {len(result.errors)} errors:")
    for error in result.errors:
        print(f"  - {error}")
else:
    print("Cleanup completed successfully")
```
