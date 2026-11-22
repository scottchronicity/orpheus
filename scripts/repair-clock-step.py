#!/usr/bin/env python3
"""Repair detections recorded before NTP stepped a wrong boot clock.

After a cold boot without a battery-backed clock, a service that starts before
NTP stamps its audio.motion rows, and names their clips, with a 1970 clock. NTP
then steps the clock by a fixed amount. Every value measured on the pre-step
clock is off by exactly that step, so adding it back recovers the time the
station would have recorded. Nothing is estimated beyond the measured step.

The step must be measured in the same boot, before any reboot. systemd records
each unit event on both CLOCK_REALTIME and CLOCK_MONOTONIC; the step is
(realtime - monotonic now) - (realtime - monotonic at a unit start before the
step). See docs/operator-manual (Data & retention) for the commands.

For each audio.motion row given with --ids (all from the same boot), this:
  - moves `timestamp` by the step, and `metadata.duration_seconds` back by it
    when the duration was measured across the step, keeping the original
    values under `metadata.clock_correction`;
  - renames its clip to the name the corrected time gives, and moves the
    clip's mtime by the step when the clip was finished on the boot clock
    (the storage sweep ages files by mtime);
  - points every detection and entity that references the old clip at the new
    name (they carry correct timestamps; only the path changes).
--purge-detections/--purge-entities delete pre-2000 rows that cannot be dated
(no clip, no measured step), keeping a full copy in the undo file.

  plan  --db DB --step S --ids A-B [--purge-...]   read-only: print the plan
  apply --db DB --step S --ids A-B --undo-file F   back up, then repair
  undo  --db DB --undo-file F                      reverse an apply exactly

apply writes the undo file first, then hard-links each clip under its new name,
then updates the database in one transaction, and only then removes the old
names. So every row always points at an existing file, and a failure at any
step leaves the database unchanged. Run it as the user that owns the data
(sudo -u orpheus). Writers may keep running: the transaction is short.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

EPOCH_CUTOFF = "2000-01-01"  # anything before this is a boot-clock timestamp
CLIP_NAME = "%Y%m%dT%H%M%S.%fZ"  # orpheus_agent_audio_motion.clip_saver
WINDOW = timedelta(hours=1)  # dependents are written within seconds of the clip
TEXT_COLUMNS = {
    "detections": ("audio_clip_path", "metadata", "event_metadata"),
    "entities": ("evidence", "context"),
}


class RepairError(Exception):
    pass


def parse_ids(spec: str) -> list[int]:
    ids: list[int] = []
    for part in filter(None, spec.split(",")):
        lo, _, hi = part.partition("-")
        ids.extend(range(int(lo), int(hi or lo) + 1))
    return ids


def connect(db: str, writable: bool) -> sqlite3.Connection:
    uri = f"file:{db}?mode={'rw' if writable else 'ro'}"
    conn = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def fetch(conn: sqlite3.Connection, table: str, row_id: int) -> dict | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def candidates(conn, table: str, first: datetime, last: datetime) -> list[dict]:
    """Rows that may reference clips starting between `first` and `last`: written
    within WINDOW after them, or themselves still on the boot clock. Both ranges
    use the timestamp index, so this reads minutes of rows, not the table."""
    lo = first.isoformat()
    hi = (last + WINDOW).isoformat()
    sql = (
        f"SELECT * FROM {table} WHERE (timestamp >= ? AND timestamp < ?) "
        f"OR timestamp < ? ORDER BY id"
    )
    return [dict(r) for r in conn.execute(sql, (lo, hi, EPOCH_CUTOFF))]


def plan_repair(conn, ids, step: float, purge_det, purge_ent) -> dict:
    if not ids and not purge_det and not purge_ent:
        raise RepairError("nothing to do: give --ids and/or --purge-*")
    if ids and not step:
        raise RepairError("--step is required with --ids")
    offset = timedelta(seconds=step)
    clips, updates = [], {"detections": {}, "entities": {}}
    for row_id in ids:
        row = fetch(conn, "detections", row_id)
        if row is None:
            raise RepairError(f"detection {row_id}: not found")
        if row["detection_type"] != "audio.motion":
            raise RepairError(f"detection {row_id}: {row['detection_type']}, not audio.motion")
        if row["timestamp"] >= EPOCH_CUTOFF:
            raise RepairError(f"detection {row_id}: {row['timestamp']} is not a boot-clock time")
        old_ts = datetime.fromisoformat(row["timestamp"])
        new_ts = old_ts + offset
        old_path = Path(row["audio_clip_path"])
        old_stamp = old_ts.strftime(CLIP_NAME)
        if not old_path.name.startswith(old_stamp):
            raise RepairError(f"detection {row_id}: clip {old_path.name} does not match its timestamp")
        extension = old_path.name[len(old_stamp):]  # ".flac"
        created = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
        if not timedelta(0) <= created - new_ts <= timedelta(hours=1):
            raise RepairError(
                f"detection {row_id}: corrected start {new_ts.isoformat()} is not shortly "
                f"before the row was written ({row['created_at']} UTC); wrong --step?"
            )
        new_path = old_path.with_name(new_ts.strftime(CLIP_NAME) + extension)
        meta = json.loads(row["metadata"] or "{}")
        correction = {
            "original_timestamp": row["timestamp"],
            "original_clip_path": str(old_path),
            "step_seconds": step,
            "reason": "recorded on the boot clock before NTP stepped it",
        }
        if float(meta.get("duration_seconds", 0)) > step / 2:  # measured across the step
            correction["original_duration_seconds"] = meta["duration_seconds"]
            meta["duration_seconds"] = round(meta["duration_seconds"] - step, 6)
        meta["clock_correction"] = correction
        updates["detections"][row_id] = {
            "timestamp": new_ts.isoformat(),
            "metadata": json.dumps(meta),
            "audio_clip_path": str(new_path),
        }
        clips.append({"old": str(old_path), "new": str(new_path), "start": new_ts})
    starts = [c["start"] for c in clips]
    for table, columns in TEXT_COLUMNS.items():  # repoint every row naming a renamed clip
        for row in candidates(conn, table, min(starts), max(starts)) if clips else []:
            for clip in clips:
                for col in columns:
                    if col not in row:
                        continue
                    current = updates[table].get(row["id"], {}).get(col, row[col])
                    if isinstance(current, str) and clip["old"] in current:
                        updates[table].setdefault(row["id"], {})[col] = current.replace(
                            clip["old"], clip["new"]
                        )
    purges = {"detections": purge_det, "entities": purge_ent}
    for table, row_ids in purges.items():
        for row_id in row_ids:
            row = fetch(conn, table, row_id)
            if row is None:
                raise RepairError(f"{table} {row_id}: not found")
            if row["timestamp"] >= EPOCH_CUTOFF:
                raise RepairError(f"{table} {row_id}: {row['timestamp']} is not a boot-clock time; not purging")
            if row_id in updates[table]:
                raise RepairError(f"{table} {row_id}: both repaired and purged")
    before = {
        table: [fetch(conn, table, i) for i in sorted(set(updates[table]) | set(purges[table]))]
        for table in TEXT_COLUMNS
    }
    return {
        "clips": [{"old": c["old"], "new": c["new"]} for c in clips],
        "updates": updates,
        "purges": purges,
        "before": before,
    }


def print_plan(plan: dict) -> None:
    for clip in plan["clips"]:
        print(f"rename  {clip['old']}\n     -> {Path(clip['new']).name}")
    for table in TEXT_COLUMNS:
        for row_id, cols in sorted(plan["updates"][table].items()):
            shown = {k: v for k, v in cols.items() if k == "timestamp"}
            print(f"update  {table} {row_id}: {', '.join(sorted(cols))} {shown or ''}".rstrip())
        for row_id in plan["purges"][table]:
            print(f"delete  {table} {row_id} (copy kept in the undo file)")


def check_files(plan: dict) -> None:
    for clip in plan["clips"]:
        if not os.path.isfile(clip["old"]):
            raise RepairError(f"clip missing: {clip['old']}")
        if os.path.lexists(clip["new"]):
            raise RepairError(f"target already exists: {clip['new']}")


def apply(db: str, plan: dict, undo_file: Path, args: argparse.Namespace) -> None:
    check_files(plan)
    if undo_file.exists():
        raise RepairError(f"undo file already exists: {undo_file}")
    record = {
        "db": os.path.abspath(db),
        "created": datetime.now(timezone.utc).isoformat(),
        "step_seconds": args.step,
        **{k: plan[k] for k in ("clips", "before", "updates", "purges")},
    }
    # A clip written entirely on the boot clock has a 1970 mtime, which the
    # storage sweep (it ages files by mtime) would delete before anything newer.
    # Record each clip's times so undo can put them back.
    record["clips"] = [
        {**clip, "atime_ns": st.st_atime_ns, "mtime_ns": st.st_mtime_ns}
        for clip, st in ((c, os.stat(c["old"])) for c in plan["clips"])
    ]
    with open(undo_file, "x") as f:
        json.dump(record, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    linked = []
    try:
        for clip in plan["clips"]:
            os.link(clip["old"], clip["new"])
            linked.append(clip["new"])
        conn = connect(db, writable=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for table in TEXT_COLUMNS:  # nothing may have changed since the plan
                for row in plan["before"][table]:
                    if fetch(conn, table, row["id"]) != row:
                        raise RepairError(f"{table} {row['id']} changed since planning; nothing applied")
                for row_id, cols in plan["updates"][table].items():
                    sets = ", ".join(f"{c} = ?" for c in cols)
                    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*cols.values(), row_id))
                for row_id in plan["purges"][table]:
                    conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    except BaseException:
        for path in linked:
            os.unlink(path)
        undo_file.unlink()
        raise
    cutoff_ns = int(datetime.fromisoformat(EPOCH_CUTOFF).replace(tzinfo=timezone.utc).timestamp()) * 10**9
    step_ns = round(args.step * 10**9)
    for clip in record["clips"]:
        if clip["mtime_ns"] < cutoff_ns:  # finished before NTP stepped the clock
            os.utime(clip["new"], ns=(clip["atime_ns"], clip["mtime_ns"] + step_ns))
        os.unlink(clip["old"])
    print(f"applied; undo with: {sys.argv[0]} undo --db {db} --undo-file {undo_file}")


def undo(db: str, undo_file: Path) -> None:
    record = json.loads(undo_file.read_text())
    for clip in record["clips"]:
        if not os.path.lexists(clip["old"]):
            os.link(clip["new"], clip["old"])
    conn = connect(db, writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table, rows in record["before"].items():
            for row in rows:
                cols = [c for c in row if c != "id"]
                if fetch(conn, table, row["id"]) is None:
                    names = ", ".join(row)
                    marks = ", ".join("?" for _ in row)
                    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))
                else:
                    sets = ", ".join(f"{c} = ?" for c in cols)
                    conn.execute(
                        f"UPDATE {table} SET {sets} WHERE id = ?", (*(row[c] for c in cols), row["id"])
                    )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    for clip in record["clips"]:
        if "mtime_ns" in clip:  # undo files from before mtimes were recorded have none
            os.utime(clip["old"], ns=(clip["atime_ns"], clip["mtime_ns"]))
        if os.path.lexists(clip["new"]):
            os.unlink(clip["new"])
    print("undone")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "apply", "undo"))
    ap.add_argument("--db", required=True)
    ap.add_argument("--step", type=float, default=0.0, help="measured NTP step, seconds")
    ap.add_argument("--ids", default="", help="audio.motion detection ids, e.g. 3710480-3710483")
    ap.add_argument("--purge-detections", default="", help="undatable pre-2000 detection ids")
    ap.add_argument("--purge-entities", default="", help="undatable pre-2000 entity ids")
    ap.add_argument("--undo-file", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.action == "undo":
            if not args.undo_file:
                raise RepairError("undo needs --undo-file")
            undo(args.db, args.undo_file)
            return 0
        conn = connect(args.db, writable=False)
        try:
            plan = plan_repair(
                conn, parse_ids(args.ids), args.step,
                parse_ids(args.purge_detections), parse_ids(args.purge_entities),
            )
        finally:
            conn.close()
        print_plan(plan)
        if args.action == "plan":
            check_files(plan)
            print("plan only; nothing changed")
            return 0
        if not args.undo_file:
            raise RepairError("apply needs --undo-file")
        apply(args.db, plan, args.undo_file, args)
        return 0
    except (RepairError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
