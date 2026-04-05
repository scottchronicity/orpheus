# Storage Cleanup Test Coverage

Comprehensive test suite for the storage cleanup system.

## Test Classes

### TestCleanupPolicy (11 tests)

Tests for `CleanupPolicy` dataclass and validation:

- ✅ Default values initialization
- ✅ Positive max_size_gb validation
- ✅ Valid strategy validation
- ✅ Trigger percent range validation
- ✅ Cleanup amount percent range validation
- ✅ Min file age non-negative validation
- ✅ Max age days positive validation
- ✅ Custom file pattern storage
- ✅ Valid policy passes validation
- ✅ Trigger percent boundary cases (0, 100, >100)
- ✅ Cleanup amount percent boundary cases (0, 100, >100)

### TestFileInfo (3 tests)

Tests for `FileInfo` creation and properties:

- ✅ Creating FileInfo from file path
- ✅ Age calculation accuracy (10-hour test with tolerance)
- ✅ File size accuracy

### TestStorageCleanup (19 tests)

Tests for main `StorageCleanup` class:

- ✅ Directory scanning (flat and nested)
- ✅ Non-existent directory handling
- ✅ Storage usage calculation
- ✅ Cleanup trigger detection
- ✅ File pattern filtering during scan
- ✅ Oldest-first strategy selection
- ✅ Largest-first strategy selection
- ✅ Random strategy selection
- ✅ Min file age enforcement
- ✅ Below-trigger-threshold behavior
- ✅ Deletion manifest creation
- ✅ Manifest data accuracy
- ✅ Dry-run mode (no actual deletion)
- ✅ Actual file deletion
- ✅ Error handling and continuation
- ✅ No eligible files scenario
- ✅ Target bytes respect (stops after reaching amount)
- ✅ Subdirectory recursion
- ✅ CleanupResult structure and to_dict()

### TestCleanupOldFilesByAge (4 tests)

Tests for age-based cleanup utility:

- ✅ Files older than max age are deleted
- ✅ Recent files are preserved
- ✅ Dry-run mode
- ✅ File pattern filtering
- ✅ Non-existent path handling
- ✅ Subdirectory recursion

### TestCleanupResultHelpers (3 tests)

Tests for `CleanupResult` helper methods:

- ✅ to_dict() conversion
- ✅ Default values
- ✅ None manifest_path handling

### TestStorageCleanupIntegration (2 tests)

Integration tests for complete workflows:

- ✅ Full cleanup workflow (scan → trigger check → cleanup → manifest)
- ✅ Strategy comparison (oldest vs largest selection)

## Coverage Summary

Total Tests: 42

### Feature Coverage

| Feature | Tests | Status |
| --------- | ------- | -------- |
| Policy Validation | 11 | ✅ Complete |
| File Scanning | 4 | ✅ Complete |
| Usage Calculation | 2 | ✅ Complete |
| Cleanup Strategies | 3 | ✅ Complete |
| File Selection | 5 | ✅ Complete |
| Manifest Creation | 2 | ✅ Complete |
| Dry Run Mode | 3 | ✅ Complete |
| Error Handling | 2 | ✅ Complete |
| Age-Based Cleanup | 4 | ✅ Complete |
| Integration Workflows | 2 | ✅ Complete |

### Edge Cases Tested

- ✅ Non-existent directories
- ✅ Empty directories
- ✅ Files too young to delete
- ✅ No files meet criteria
- ✅ Storage below trigger threshold
- ✅ Boundary values (0, 100, >100)
- ✅ Negative values
- ✅ Nested directory structures
- ✅ File pattern matching
- ✅ Different file sizes and ages
- ✅ Multiple strategies on same data

### Safety Mechanisms Tested

- ✅ Minimum file age protection
- ✅ Dry-run mode (no modifications)
- ✅ Manifest creation before deletion
- ✅ Error continuation (doesn't abort on single file failure)
- ✅ Trigger threshold respect
- ✅ Target bytes respect (stops when enough freed)

## Test Data Patterns

### Temporal Data

- Files 1-10 hours old
- Files 2-5 days old  
- Files 30-31 days old
- Mix of old and recent files

### Size Variations

- Small files (100 bytes)
- Medium files (1 KB)
- Large files (10 KB)
- Very large files (1 MB)

### Directory Structures

- Flat directory
- Single subdirectory
- Nested subdirectories (3 levels)
- Mixed file types (.txt, .flac, .json)

## Running Tests

```bash
# Run all cleanup tests
pytest tests/test_storage_cleanup.py -v

# Run specific test class
pytest tests/test_storage_cleanup.py::TestCleanupPolicy -v

# Run with coverage
pytest tests/test_storage_cleanup.py --cov=orpheus_common.storage.cleanup --cov-report=html

# Run integration tests only
pytest tests/test_storage_cleanup.py::TestStorageCleanupIntegration -v
```

## Test Fixtures

All tests use `tempfile.TemporaryDirectory()` for isolation:

- No test leaves files behind
- No interference between tests
- Safe to run in parallel
- Can run on any OS

## Assertions Used

- Value equality (`==`, `!=`)
- Numeric comparisons (`>`, `<`, `>=`)
- Existence checks (`.exists()`)
- Type checks (`isinstance()`)
- Collection membership (`in`)
- Exception matching (`pytest.raises`)
- Approximate equality for timing (`abs(x - y) < tolerance`)

## Future Test Enhancements

Potential additions:

- [ ] Performance tests with large file counts (10,000+ files)
- [ ] Concurrent cleanup tests (multiple instances)
- [ ] Symbolic link handling
- [ ] Permission denied scenarios
- [ ] Disk full scenarios
- [ ] Very large files (>1 GB)
- [ ] Different filesystems behavior
- [ ] Network filesystem scenarios
