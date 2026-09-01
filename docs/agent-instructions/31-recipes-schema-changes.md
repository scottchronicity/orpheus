# 31 — Recipe: adding a schema field

When you add a new field to a Pydantic model that gets persisted
(Detection, Entity, EntityEvidence, etc), you MUST touch all of the
following. A missed step is a silent persistence bug — you'll save
the field successfully, but read-back returns `None`.

Use this as a checklist. The full design + worked example is in
[`22-schema-and-migrations.md`](22-schema-and-migrations.md).

## Step 1 — Pydantic model

`platform/orpheus-common/src/orpheus_common/detection/models.py`

```python
class Detection(OrpheusBaseEvent):
    ...
    # New field — Optional with default so legacy rows / MQTT payloads
    # without it still parse.
    new_field: Optional[str] = None
```

Use `Optional[T] = None` unless you're certain a sensible non-None
default exists.

## Step 2 — `to_dict()`

```python
def to_dict(self) -> dict[str, Any]:
    return {
        ...,
        "new_field": self.new_field,
    }
```

## Step 3 — `from_dict()`

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> Detection:
    kwargs: dict[str, Any] = {
        ...,
        "new_field": data.get("new_field"),
    }
    ...
```

`.get()` — not `[]` — because old payloads won't have the key.

## Step 4 — `CREATE TABLE` (for fresh DBs)

`database.py` `_init_schema`:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        ...,
        new_field TEXT,
        ...
    )
""")
```

## Step 5 — `ensure_schema_updates()` (for existing DBs)

Same file. Additive ALTER TABLE, idempotent:

```python
cursor.execute("PRAGMA table_info(detections)")
existing_columns = {row[1] for row in cursor.fetchall()}
if "new_field" not in existing_columns:
    cursor.execute("ALTER TABLE detections ADD COLUMN new_field TEXT")
```

If your field is heavily queried, also create an index:

```python
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_new_field "
    "ON detections(new_field)"
)
```

## Step 6 — `save_<thing>()` INSERT

```python
cursor.execute(
    """
    INSERT INTO detections (
        ...,
        new_field
    ) VALUES (?, ?, ?, ..., ?)
""",
    (
        ...,
        detection.new_field,
    ),
)
```

## Step 7 — `_row_to_<thing>()` SELECT

```python
@staticmethod
def _row_to_detection(row: sqlite3.Row) -> Detection:
    # Guard for the partial-schema test case: row.keys() check
    # protects against tests that init only some tables.
    new_field_val = None
    if "new_field" in row.keys():
        new_field_val = row["new_field"]

    kwargs = {
        ...,
        "new_field": new_field_val,
    }
    return Detection(...)
```

## Step 8 — Tests

`platform/orpheus-common/tests/test_detection_database.py`:

```python
def test_new_field_round_trips(self, db: DetectionDB) -> None:
    """The new field survives save → load."""
    det = Detection(
        event_id="rt_001",
        timestamp=datetime.now(timezone.utc),
        detection_type="species.detected",
        new_field="canary-value",
    )
    db.save(det)
    loaded = db.get_by_event_id("rt_001")
    assert loaded.new_field == "canary-value"

def test_new_field_handles_legacy_rows(self, db: DetectionDB) -> None:
    """Pre-migration rows (NULL new_field) load with new_field=None."""
    # ... insert a row directly via raw SQL without setting new_field
    # ... query via db.get_by_event_id
    # ... assert loaded.new_field is None
```

## Step 9 — Downstream consumers

If anything downstream reads the field (the correlator, the UI
backend, a different agent), update them too. The pre-PR checklist:

```bash
grep -rn "old_field_name\|model.attr_to_remove" \
    platform/ services/ agents/ docs/
```

## Step 10 — Verify

```bash
make test-common                 # all schema tests pass
make test-all                    # nothing else broke
```

## Worked example

The "Layer 1.5 + Layer 2 persistence" commit (`1bb7fcd`) adds three
new fields at once:
- `Detection.root_event_id`
- `Entity.event_signature` (dict)
- Per-evidence taxonomy on `EntityEvidence`

Read its diff for a working example of all 10 steps at once.

## See also

- [`22-schema-and-migrations.md`](22-schema-and-migrations.md) —
  the design rules.
- [`99-gotchas.md`](99-gotchas.md) — SQLite landmines.
