# Storage Cleanup System

Automatic retention management for Orpheus platform storage.

## Overview

The storage cleanup system provides configurable, automatic cleanup of old files based on retention policies. It supports multiple cleanup strategies and includes safety mechanisms to prevent data loss.

## Features

- **Multiple Cleanup Strategies**: Oldest-first, largest-first, or random selection
- **Configurable Triggers**: Cleanup based on storage usage percentage
- **Safety Mechanisms**: Minimum file age, deletion manifests, dry-run mode
- **Flexible Policies**: Configure size limits, age limits, and cleanup amounts
- **Integration Ready**: Easy integration with async agents and services

## Quick Start

### Simple Age-Based Cleanup

```python
from pathlib import Path
from orpheus_common.storage import cleanup_old_files_by_age

# Remove files older than 90 days
deleted = cleanup_old_files_by_age(
    path=Path("/data/orpheus/audio/clips"),
    max_age_days=90,
    dry_run=False
)
```

### Policy-Based Cleanup

```python
from pathlib import Path
from orpheus_common.storage import CleanupPolicy, StorageCleanup

# Create cleanup policy
policy = CleanupPolicy(
    max_size_gb=50.0,                   # Storage limit
    cleanup_trigger_percent=90.0,        # Trigger at 90% full
    cleanup_amount_percent=25.0,         # Remove 25% when triggered
    cleanup_strategy="oldest",           # Remove oldest files first
    min_file_age_hours=1.0,              # Never delete files < 1 hour old
)

# Execute cleanup
cleanup = StorageCleanup(policy)
result = cleanup.cleanup(
    path=Path("/data/orpheus/audio/clips"),
    dry_run=False
)

print(f"Removed {result.files_removed} files")
print(f"Freed {result.bytes_freed / (1024**2):.2f} MB")
```

## Configuration

Add to `orpheus.yaml`:

```yaml
storage:
  retention:
    raw_audio_days: 30
    raw_video_days: 30
    detections_days: 365
    # Cleanup settings
    max_size_gb: 50.0
    cleanup_trigger_percent: 90.0
    cleanup_amount_percent: 25.0
    cleanup_strategy: "oldest"
    check_interval_hours: 6.0
    min_file_age_hours: 1.0
```

## Cleanup Strategies

### Oldest (Default)
Removes files by modification time, oldest first. Best for time-series data.

```python
CleanupPolicy(cleanup_strategy="oldest")
```

### Largest
Removes largest files first. Maximizes space freed per deletion.

```python
CleanupPolicy(cleanup_strategy="largest")
```

### Random
Random selection. Useful for creating unbiased reduced datasets.

```python
CleanupPolicy(cleanup_strategy="random")
```

## Integration Examples

### Periodic Cleanup Task

```python
import asyncio
from orpheus_common.storage import CleanupPolicy, StorageCleanup

class MyAgent:
    async def _periodic_cleanup(self):
        """Run cleanup every N hours."""
        interval = self.config.storage.retention.check_interval_hours * 3600
        
        while True:
            await asyncio.sleep(interval)
            
            policy = CleanupPolicy(
                max_size_gb=self.config.storage.retention.max_size_gb,
                cleanup_strategy=self.config.storage.retention.cleanup_strategy,
                # ... other settings from config
            )
            
            cleanup = StorageCleanup(policy)
            result = cleanup.cleanup(self.storage_path, dry_run=False)
            
            if result.files_removed > 0:
                logger.info(f"Cleanup freed {result.bytes_freed / (1024**2):.2f} MB")
```

### Manual Cleanup

```python
from orpheus_common.storage import CleanupPolicy, StorageCleanup

policy = CleanupPolicy(
    max_size_gb=50.0,
    cleanup_trigger_percent=90.0,
    cleanup_amount_percent=25.0,
)

cleanup = StorageCleanup(policy)
result = cleanup.cleanup(path, dry_run=True)  # Preview first

if result.files_removed > 0:
    print(f"Would delete {result.files_removed} files")
    # Review manifest, then run with dry_run=False
```

## API Reference

### CleanupPolicy

Configuration for cleanup behavior:

- `max_size_gb`: Storage limit before cleanup triggers
- `max_age_days`: Maximum file age (informational)
- `cleanup_strategy`: `"oldest"`, `"largest"`, or `"random"`
- `cleanup_trigger_percent`: Trigger cleanup at this % of max_size_gb
- `cleanup_amount_percent`: Remove this % of files when triggered
- `min_file_age_hours`: Never delete files younger than this
- `file_pattern`: Glob pattern for files to consider (e.g., `"*.flac"`)

### StorageCleanup

Main cleanup manager:

- `scan_directory(path)`: Scan and collect file information
- `calculate_usage(path)`: Calculate current usage vs limit
- `needs_cleanup(path)`: Check if cleanup should run
- `select_files_to_delete(files)`: Select files based on strategy
- `cleanup(path, dry_run, manifest_dir)`: Execute cleanup operation

### CleanupResult

Result of cleanup operation:

- `files_removed`: Number of files deleted
- `bytes_freed`: Bytes freed by deletion
- `manifest_path`: Path to CSV manifest of deleted files
- `duration_seconds`: Time taken for operation
- `errors`: List of any errors encountered

## Safety Features

1. **Minimum File Age**: Files younger than `min_file_age_hours` are never selected
2. **Deletion Manifests**: CSV log created before any files are deleted
3. **Dry Run Mode**: Preview operations without making changes
4. **Error Resilience**: Continues on individual file errors, logs everything
5. **Validation**: Policy validation ensures sensible configuration

## Testing

Comprehensive test suite in `tests/test_storage_cleanup.py`:

```bash
pytest tests/test_storage_cleanup.py -v
```

## Examples

See `examples/cleanup_demo.py` for a complete demonstration:

```bash
# Check storage usage
python examples/cleanup_demo.py /data/orpheus/audio --mode check

# Demo policy-based cleanup (dry-run)
python examples/cleanup_demo.py /data/orpheus/audio --mode policy --dry-run

# Demo age-based cleanup
python examples/cleanup_demo.py /data/orpheus/audio --mode age --max-age-days 90 --dry-run
```

## Documentation

- [Integration Guide](docs/STORAGE_CLEANUP.md) - Detailed integration instructions
- [API Documentation](src/orpheus_common/storage/cleanup.py) - Full API reference with docstrings

## Files

```
src/orpheus_common/storage/
├── __init__.py          # Exports cleanup classes
├── cleanup.py           # Main implementation
└── paths.py             # Storage path utilities

tests/
└── test_storage_cleanup.py  # Comprehensive tests

docs/
└── STORAGE_CLEANUP.md   # Integration guide

examples/
└── cleanup_demo.py      # Interactive demo script
```

## Requirements

- Python 3.9+
- Part of `orpheus-common` platform package
- No external dependencies beyond stdlib

## License

Part of the Orpheus platform. See LICENSE in repository root.
