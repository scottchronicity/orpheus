#!/usr/bin/env bats
# scripts/repair-clock-step.py: rows and clips recorded on a 1970 boot clock are
# moved by the measured NTP step, every reference follows the renamed clip, and
# undo restores the database and the file names exactly. The sandbox mirrors
# jetson1's 2026-11-21 cold boot.

load 'test_helper'

TOOL="$REPO_ROOT/scripts/repair-clock-step.py"
STEP=1795291600.141334

setup() {
  SB="$BATS_TEST_TMPDIR"
  DB="$SB/orpheus.db"
  CLIPS="$SB/audio/audio_motion"
  mkdir -p "$CLIPS/1" "$CLIPS/2"
  echo one > "$CLIPS/1/19700101T000047.598402Z.flac"
  echo later > "$CLIPS/2/20261121T200749.628000Z.flac"
  python3 - "$DB" "$CLIPS" <<'EOF'
import json, sqlite3, sys
db, clips = sys.argv[1:]
c = sqlite3.connect(db)
c.execute("PRAGMA journal_mode=WAL")
c.execute("""CREATE TABLE detections (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
  timestamp TEXT NOT NULL, detection_type TEXT NOT NULL, channel INTEGER, species_code TEXT,
  audio_clip_path TEXT, metadata TEXT, source_event_id TEXT, created_at TEXT, event_metadata TEXT)""")
c.execute("CREATE INDEX idx_timestamp ON detections(timestamp)")
c.execute("""CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT UNIQUE NOT NULL,
  timestamp TEXT NOT NULL, species TEXT NOT NULL, evidence TEXT, context TEXT, created_at TEXT)""")
c.execute("CREATE INDEX idx_entity_timestamp ON entities(timestamp)")
bad = f"{clips}/1/19700101T000047.598402Z.flac"
good = f"{clips}/2/20261121T200749.628000Z.flac"
meta = {"duration_seconds": 1795291621.58581, "frame_count": 1023}
rows = [
  (10, "motion", "1970-01-01T00:00:47.598402+00:00", "audio.motion", 1, None, bad, json.dumps(meta), None, "2026-11-21 20:07:49", '{"event_timestamp": "2026-11-21T20:07:49.595414+00:00"}'),
  (11, "bird", "2026-11-21T20:07:52.376651+00:00", "species.detected", 1, "baeolo", bad, '{"start_time": 9.0}', "x", "2026-11-21 20:07:52", None),
  (12, "other", "2026-11-21T20:08:30.000000+00:00", "audio.motion", 2, None, good, "{}", None, "2026-11-21 20:08:30", None),
  (13, "march", "1970-01-01T00:01:23.784234+00:00", "species.detected", 2, "larusa", f"{clips}/2/19700101T000049.714276Z.flac", "{}", "y", "1970-01-01 00:01:23", None),
]
c.executemany("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
c.execute("INSERT INTO entities VALUES (5, 'e-bird', '2026-11-21T20:08:01.424923+00:00', 'baeolo', ?, NULL, '2026-11-21 20:08:01')",
          (json.dumps([{"event_id": "bird", "clip_path": bad, "confidence": 0.3}]),))
c.execute("INSERT INTO entities VALUES (6, 'e-march', '1970-01-01T00:01:26.864826+00:00', 'larusa', '[]', NULL, '1970-01-01 00:01:26')")
c.commit(); c.close()
EOF
}

dump() {
  python3 - "$DB" <<'EOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
for t in ("detections", "entities"):
    for r in c.execute(f"SELECT * FROM {t} ORDER BY id"): print(t, r)
EOF
}

q() { python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchone()[0])" "$DB" "$1"; }

@test "plan changes nothing and names the corrected time" {
  before=$(dump)
  run python3 "$TOOL" plan --db "$DB" --step "$STEP" --ids 10
  [ "$status" -eq 0 ]
  [[ "$output" == *"-> 20261121T200727.739736Z.flac"* ]]
  [[ "$output" == *"update  detections 11: audio_clip_path"* ]]
  [[ "$output" == *"update  entities 5: evidence"* ]]
  [ "$(dump)" = "$before" ]
  [ -f "$CLIPS/1/19700101T000047.598402Z.flac" ]
}

@test "apply moves the row by the step, renames the clip and repoints every reference" {
  run python3 "$TOOL" apply --db "$DB" --step "$STEP" --ids 10 --undo-file "$SB/undo.json"
  [ "$status" -eq 0 ]
  new="$CLIPS/1/20261121T200727.739736Z.flac"
  [ "$(cat "$new")" = one ]
  [ ! -e "$CLIPS/1/19700101T000047.598402Z.flac" ]
  [ "$(q "SELECT timestamp FROM detections WHERE id=10")" = "2026-11-21T20:07:27.739736+00:00" ]
  [ "$(q "SELECT audio_clip_path FROM detections WHERE id=10")" = "$new" ]
  [ "$(q "SELECT audio_clip_path FROM detections WHERE id=11")" = "$new" ]
  [ "$(q "SELECT json_extract(evidence, '\$[0].clip_path') FROM entities WHERE id=5")" = "$new" ]
  [ "$(q "SELECT json_extract(metadata, '\$.duration_seconds') FROM detections WHERE id=10")" = "21.444476" ]
  [ "$(q "SELECT json_extract(metadata, '\$.clock_correction.original_timestamp') FROM detections WHERE id=10")" = "1970-01-01T00:00:47.598402+00:00" ]
  [ "$(q "SELECT json_extract(metadata, '\$.frame_count') FROM detections WHERE id=10")" = "1023" ]
  # rows that never referenced the clip are untouched
  [ "$(q "SELECT timestamp FROM detections WHERE id=11")" = "2026-11-21T20:07:52.376651+00:00" ]
  [ "$(q "SELECT audio_clip_path FROM detections WHERE id=12")" = "$CLIPS/2/20261121T200749.628000Z.flac" ]
  [ "$(q "SELECT count(*) FROM detections WHERE audio_clip_path LIKE '%19700101T000047%'")" = "0" ]
}

@test "undo restores the database and the clip name exactly" {
  before=$(dump)
  python3 "$TOOL" apply --db "$DB" --step "$STEP" --ids 10 --purge-detections 13 --purge-entities 6 --undo-file "$SB/undo.json"
  [ "$(dump)" != "$before" ]
  run python3 "$TOOL" undo --db "$DB" --undo-file "$SB/undo.json"
  [ "$status" -eq 0 ]
  [ "$(dump)" = "$before" ]
  [ "$(cat "$CLIPS/1/19700101T000047.598402Z.flac")" = one ]
  [ ! -e "$CLIPS/1/20261121T200727.739736Z.flac" ]
}

@test "purge deletes undatable 1970 rows and keeps them in the undo file" {
  run python3 "$TOOL" apply --db "$DB" --purge-detections 13 --purge-entities 6 --undo-file "$SB/undo.json"
  [ "$status" -eq 0 ]
  [ "$(q "SELECT count(*) FROM detections WHERE timestamp < '2000'")" = "1" ]   # row 10, not asked for
  [ "$(q "SELECT count(*) FROM entities WHERE id=6")" = "0" ]
  grep -q '"larusa"' "$SB/undo.json"
}

@test "refuses to repair or purge a row that is not on the boot clock" {
  before=$(dump)
  run python3 "$TOOL" apply --db "$DB" --step "$STEP" --ids 12 --undo-file "$SB/undo.json"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a boot-clock time"* ]]
  run python3 "$TOOL" apply --db "$DB" --purge-detections 11 --undo-file "$SB/undo.json"
  [ "$status" -eq 1 ]
  [ "$(dump)" = "$before" ]
  [ ! -e "$SB/undo.json" ]
}

@test "refuses a step that does not land just before the row was written" {
  run python3 "$TOOL" plan --db "$DB" --step 1795280000 --ids 10
  [ "$status" -eq 1 ]
  [[ "$output" == *"wrong --step?"* ]]
}

@test "refuses when the corrected name already exists, changing nothing" {
  echo clash > "$CLIPS/1/20261121T200727.739736Z.flac"
  before=$(dump)
  run python3 "$TOOL" apply --db "$DB" --step "$STEP" --ids 10 --undo-file "$SB/undo.json"
  [ "$status" -eq 1 ]
  [[ "$output" == *"target already exists"* ]]
  [ "$(dump)" = "$before" ]
  [ -f "$CLIPS/1/19700101T000047.598402Z.flac" ]
  [ ! -e "$SB/undo.json" ]
}

@test "a database failure after the clips were linked leaves no change and no stray link" {
  chmod a-w "$DB"   # the transaction fails; the new hard links already exist
  run python3 "$TOOL" apply --db "$DB" --step "$STEP" --ids 10 --undo-file "$SB/undo.json"
  chmod u+w "$DB"
  [ "$status" -eq 1 ]
  [ -f "$CLIPS/1/19700101T000047.598402Z.flac" ]
  [ ! -e "$CLIPS/1/20261121T200727.739736Z.flac" ]
  [ ! -e "$SB/undo.json" ]
  [ "$(q "SELECT timestamp FROM detections WHERE id=10")" = "1970-01-01T00:00:47.598402+00:00" ]
}
