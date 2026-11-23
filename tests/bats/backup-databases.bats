#!/usr/bin/env bats
# scripts/backup-databases.py — SQLite backups without the sqlite3 CLI.
# Everything runs in a sandbox data root and config dir; a live WAL-mode
# writer stays open during the backup, as the agents would be.

load 'test_helper'

TOOL="$REPO_ROOT/scripts/backup-databases.py"

setup() {
  SB="$BATS_TEST_TMPDIR"
  DATA="$SB/data"
  CONF="$SB/config"
  mkdir -p "$DATA/detections" "$CONF"
  python3 - "$DATA" <<'EOF'
import sqlite3, sys
root = sys.argv[1]
c = sqlite3.connect(f"{root}/detections/orpheus.db")
c.execute("PRAGMA journal_mode=WAL")
c.execute("CREATE TABLE detections (id INTEGER PRIMARY KEY, species TEXT)")
c.executemany("INSERT INTO detections (species) VALUES (?)", [("crow",)] * 50)
c.commit(); c.close()
u = sqlite3.connect(f"{root}/users.db")
u.execute("CREATE TABLE users (name TEXT)"); u.execute("INSERT INTO users VALUES ('a')"); u.commit(); u.close()
EOF
  : > "$DATA/detections/detections.db"
  echo "retention: {}" > "$CONF/orpheus.yaml"
  echo "ORPHEUS_EVENT_BUS__NATS_URL=nats://u:p@host:4222" > "$CONF/.env"
  chmod 600 "$CONF/.env"
  DEST="$SB/backups/b1"
}

backup() { run python3 "$TOOL" --data-root "$DATA" --config-dir "$CONF" --dest "$DEST" "$@"; }

@test "backs up every database and the config, with checksums sha256sum accepts" {
  backup
  assert_success
  assert_output --partial "backup complete"
  [ -f "$DEST/orpheus.db" ] && [ -f "$DEST/users.db" ] && [ -f "$DEST/orpheus.yaml" ]
  [ "$(stat -c '%a' "$DEST/.env")" = "600" ]
  (cd "$DEST" && sha256sum -c --quiet SHA256SUMS)
  python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m["databases"]["orpheus.db"]["tables"]["detections"] == 50' "$DEST/manifest.json"
}

@test "run as root, the database copies go to the data root's owner but the config copies do not" {
  # The data root's owner is the service user; .env holds the station's secrets.
  run python3 - "$TOOL" "$DATA" "$CONF" "$DEST" <<'PY'
import importlib.util, os, sys
tool, data, conf, dest = sys.argv[1:]
spec = importlib.util.spec_from_file_location("backup_databases", tool)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
chowned = []
mod.os.geteuid = lambda: 0
mod.os.chown = lambda path, uid, gid: chowned.append(os.path.basename(str(path)))
assert mod.main(["--data-root", data, "--config-dir", conf, "--dest", dest]) == 0
print(sorted(chowned))
PY
  assert_success
  assert_output --partial "'orpheus.db'"
  assert_output --partial "'SHA256SUMS'"
  refute_output --partial "'.env'"
  refute_output --partial "'orpheus.yaml'"
}

@test "an empty database file is listed and skipped, not backed up" {
  backup
  assert_success
  assert_output --partial "skipped   $DATA/detections/detections.db  (empty file)"
  [ ! -e "$DEST/detections.db" ]
}

@test "rows still only in the WAL of a live writer are in the snapshot, and the source is not written" {
  python3 - "$DATA" "$SB/hold" <<'EOF' &
import os, sqlite3, sys, time
c = sqlite3.connect(f"{sys.argv[1]}/detections/orpheus.db")
c.execute("PRAGMA wal_autocheckpoint=0")
c.executemany("INSERT INTO detections (species) VALUES (?)", [("jay",)] * 7)
c.commit()
open(sys.argv[2], "w").close()
time.sleep(30)
EOF
  writer=$!
  for _ in $(seq 1 100); do [ -e "$SB/hold" ] && break; sleep 0.1; done
  [ -s "$DATA/detections/orpheus.db-wal" ]
  before=$(sha256sum "$DATA/detections/orpheus.db" | cut -d' ' -f1)
  backup
  after=$(sha256sum "$DATA/detections/orpheus.db" | cut -d' ' -f1)
  kill "$writer" 2>/dev/null || true
  assert_success
  [ "$before" = "$after" ]
  run python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("SELECT count(*) FROM detections WHERE species=\"jay\"").fetchone()[0])' "$DEST/orpheus.db"
  assert_output "7"
}

@test "an existing directory with other captures in it is used; one holding a backup is refused" {
  mkdir -p "$DEST/config-before-review"; echo state > "$DEST/unit-state.txt"
  backup
  assert_success
  [ -f "$DEST/orpheus.db" ] && [ -f "$DEST/unit-state.txt" ]
  before=$(sha256sum "$DEST/orpheus.db")
  backup
  assert_failure
  assert_output --partial "refusing to mix backups"
  assert_output --partial "SHA256SUMS"
  [ "$(sha256sum "$DEST/orpheus.db")" = "$before" ]
}

@test "dry run writes nothing" {
  backup --dry-run
  assert_success
  assert_output --partial "dry run: nothing was written"
  [ ! -e "$DEST" ]
}

@test "verify passes a good backup and catches a changed or missing file" {
  backup
  assert_success
  run python3 "$TOOL" --verify "$DEST"
  assert_success
  assert_output --partial "verified"
  printf 'x' >> "$DEST/users.db"
  run python3 "$TOOL" --verify "$DEST"
  assert_failure
  assert_output --partial "users.db: sha256 mismatch"
  mv "$DEST/orpheus.yaml" "$SB/elsewhere.yaml"
  run python3 "$TOOL" --verify "$DEST"
  assert_output --partial "orpheus.yaml: missing"
}

@test "a database that is not SQLite fails the backup and is not renamed into place" {
  echo "not a database at all, just text that is long enough" > "$DATA/broken.db"
  backup
  assert_failure
  assert_output --partial "snapshot failed"
  assert_output --partial "backup INCOMPLETE"
  [ ! -e "$DEST/broken.db" ]
  [ -f "$DEST/orpheus.db" ]
}

@test "databases with the same name in two directories do not overwrite each other" {
  cp "$DATA/users.db" "$DATA/detections/users.db"
  backup
  assert_success
  [ -f "$DEST/users.db" ] && [ -f "$DEST/detections-users.db" ]
}
