# ADR 0005: Event-Driven Architecture with JSON Sidecar Persistence

**Status:** Accepted

**Superseded in part by** [ADR 0006](0006-event-hierarchy-and-taxonomy.md): the
`InferenceEvent` layer described here is now an alias. The JSON sidecar and the
migration path remain live.

**Date:** 2026-02-13

**Deciders:** Development Team

## Context

The Orpheus system processes multiple signal types (audio motion, bird detections, crow analysis) through a chain of agents. Previously, each agent used ad-hoc dict payloads with no shared schema for event lineage or spatiotemporal context. This made it difficult to:

1. **Trace event lineage**: Which audio event triggered which bird detection?
2. **Attach location context**: GPS coordinates from the GPS service weren't linked to detection events.
3. **Evolve the schema safely**: Adding new fields required brittle ALTER TABLE migrations that could break rollbacks.

### Requirements

- All events share a common base with `event_id`, `event_timestamp`, and optional `SpatiotemporalContext`
- Inference events link back to their source sensory event via `source_event_id`
- Schema changes must be backward and forward compatible
- Old JSON payloads (missing new fields) must deserialize without error
- Old code (missing new column awareness) must not crash on rollback

## Decision

### 1. Base Event System (Pydantic v2)

Introduce `OrpheusBaseEvent` and `InferenceEvent` in `src/orpheus_common/events.py`:

- **`SpatiotemporalContext`**: Optional GPS coordinates (`lat`, `lon`, `elevation`), `timestamp`, and `sensor_id`
- **`OrpheusBaseEvent`**: `event_id` (UUID v4 default), `event_timestamp` (UTC default), optional `context`
- **`InferenceEvent`**: Adds `source_event_id` for lineage tracking

The existing `Detection` model inherits from `InferenceEvent`, gaining all base fields while maintaining its existing API.

### 2. JSON Sidecar Persistence Pattern

Instead of adding multiple columns for context/lineage fields (lat, lon, elevation, sensor_id, event_timestamp, etc.), we add **one** column:

```sql
ALTER TABLE detections ADD COLUMN event_metadata TEXT;
```

This `event_metadata` column stores a JSON blob containing:

- `event_id` (redundant with the main column, for completeness)
- `source_event_id`
- `event_timestamp`
- `context` (the full SpatiotemporalContext as JSON)

**Save path**: Serialize context and lineage fields into `event_metadata` JSON.
**Load path**: Deserialize `event_metadata` back into Pydantic model fields.

### 3. Safe Schema Migration

`ensure_schema_updates(db_path)` runs on startup:

1. Checks `PRAGMA table_info(detections)` for existing columns
2. If `event_metadata` is missing, executes `ALTER TABLE ... ADD COLUMN event_metadata TEXT`
3. Idempotent: safe to run multiple times

## Consequences

### Positive

- **Backward compatible**: Old JSON payloads without `context` or `event_id` deserialize with defaults (auto-generated UUID, None context)
- **Forward compatible**: New fields can be added to `event_metadata` JSON without schema changes
- **Safe rollback**: If code is rolled back, the `event_metadata` column remains in SQLite but is ignored by the old ORM, preventing crashes (SQLite does not error on extra columns)
- **Single migration**: One `ALTER TABLE ADD COLUMN` instead of many
- **Event lineage**: Full traceability from audio → bird detection → crow analysis

### Negative

- **No SQL queries on context fields**: GPS coordinates are inside JSON, so you cannot do `WHERE lat > 47.0` directly (would need JSON functions or a future migration)
- **Slight redundancy**: `event_id` and `source_event_id` exist in both the main columns and `event_metadata`

### Neutral

- **Detection model changed from dataclass to Pydantic**: All existing constructor patterns (`Detection(event_id=..., ...)`) continue to work identically
- **Migration is additive only**: No columns removed, no data lost

## Rollback Strategy

If a rollback to pre-event-system code is needed:

1. **Code rollback**: Revert to the old `Detection` dataclass. The old code does not reference `event_metadata` and SQLite ignores the extra column during reads.
2. **Database**: The `event_metadata` column remains in the SQLite file but is never read or written. No data corruption occurs.
3. **JSON payloads**: Old MQTT consumers ignore unknown fields in JSON payloads.
4. **Re-upgrade**: When upgrading again, `ensure_schema_updates` detects the column already exists and skips the migration.

## Appendix: Manual Verification Guide

### A. MacBook Dev Environment

```bash
# 1. Install and run tests
cd platform/orpheus-common
make install-dev
make test

# 2. Verify the event_metadata column exists in a test DB
python3 -c "
from pathlib import Path
from orpheus_common.detection import DetectionDB
import tempfile, sqlite3
with tempfile.TemporaryDirectory() as td:
    db = DetectionDB(db_path=Path(td) / 'test.db')
    conn = sqlite3.connect(str(Path(td) / 'test.db'))
    cols = {r[1] for r in conn.execute('PRAGMA table_info(detections)').fetchall()}
    assert 'event_metadata' in cols, 'event_metadata column missing!'
    print('✅ event_metadata column present')
    conn.close()
"

# 3. Verify round-trip with context
python3 -c "
from datetime import datetime, timezone
from pathlib import Path
from orpheus_common.detection import Detection, DetectionDB
from orpheus_common.events import SpatiotemporalContext
import tempfile
with tempfile.TemporaryDirectory() as td:
    db = DetectionDB(db_path=Path(td) / 'test.db')
    ctx = SpatiotemporalContext(lat=47.6062, lon=-122.3321, sensor_id='mic-01')
    det = Detection(
        event_id='verify_001',
        timestamp=datetime.now(timezone.utc),
        detection_type='species.detected',
        species_code='amecro',
        confidence=0.95,
        context=ctx,
    )
    db.save(det)
    loaded = db.get_by_event_id('verify_001')
    assert loaded.context.lat == 47.6062
    assert loaded.context.lon == -122.3321
    print('✅ GPS context round-trip verified')
"
```

### B. Jetson Production Environment

```bash
# 1. SSH into Jetson
ssh orpheus@<jetson-ip>

# 2. Activate venv and update orpheus-common
cd /opt/orpheus/platform/orpheus-common
source venv/bin/activate
pip install -e .

# 3. Verify migration on existing database
python3 -c "
from pathlib import Path
from orpheus_common.detection.database import ensure_schema_updates
import sqlite3

db_path = Path('/data/orpheus/detections/orpheus.db')
if db_path.exists():
    ensure_schema_updates(db_path)
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute('PRAGMA table_info(detections)').fetchall()}
    conn.close()
    assert 'event_metadata' in cols
    print('✅ Production DB migrated successfully')
else:
    print('⚠️  No existing database found (will be created on first use)')
"

# 4. Verify existing data is intact
python3 -c "
from orpheus_common.detection import DetectionDB
db = DetectionDB()
results = db.query(limit=5)
print(f'✅ Loaded {len(results)} existing detections without error')
for r in results:
    print(f'  - {r.event_id}: {r.species_code} ({r.confidence})')
"

# 5. Restart services to pick up changes
sudo systemctl restart orpheus-agent-bird-detection
sudo systemctl restart orpheus-agent-crow-detection
```

## Related

- [ADR 0001: Documentation and Instruction Consolidation](0001-documentation-and-instruction-consolidation.md)
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
- [docs/Orpheus_Standard_Data_Models.md](../Orpheus_Standard_Data_Models.md)
