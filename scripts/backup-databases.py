#!/usr/bin/env python3
"""Consistent backups of every Orpheus SQLite database, without the sqlite3 CLI.

The rollout and upgrade runbooks used ``sudo sqlite3 DB "VACUUM INTO ..."``,
but a JetPack install has no ``sqlite3`` binary; the stdlib module does the same
thing. Standard library only, Python 3.8+ (the system ``python3`` on JetPack 5).

    sudo python3 scripts/backup-databases.py [--dest DIR] [--dry-run]
    sudo python3 scripts/backup-databases.py --verify DIR

Backup, per database (``<data-root>/*.db`` and ``<data-root>/detections/*.db``;
empty files are listed and skipped):

1. ``VACUUM INTO`` a ``.partial`` file from a read-only connection: a
   consistent snapshot that includes committed WAL content, with no downtime
   and no write to the live database. (A plain ``cp`` of a live WAL database
   copies a torn or stale file.)
2. ``PRAGMA integrity_check`` on the copy (``--quick`` for ``quick_check``).
3. Rename into place, record size, table row counts and sha256.

Then the runtime config (``orpheus.yaml``, and ``.env`` with its mode kept) is
copied, ``SHA256SUMS`` (``sha256sum -c`` compatible) and ``manifest.json`` are
written, and when run as root everything is chowned to the data root's owner
like the backups before it. The destination may already exist (e.g. holding
the unit-state capture taken just before) but must not contain any file this
backup writes, and there must be room for the databases plus a margin, or
nothing is written.

``--verify DIR`` re-checks a finished backup (sha256 and integrity) before you
restore from it. Exit status is non-zero if anything failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_DATA_ROOT = Path("/data/orpheus")
DEFAULT_CONFIG_DIR = Path("/opt/orpheus/config")
CONFIG_FILES = ("orpheus.yaml", ".env")
FREE_SPACE_MARGIN = 1.10  # VACUUM INTO output is at most the source size


def log(msg: str) -> None:
    print(msg, flush=True)


def find_databases(data_root: Path) -> List[Path]:
    found = set()
    for pattern in ("*.db", "detections/*.db"):
        found.update(p for p in data_root.glob(pattern) if p.is_file())
    return sorted(found)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def live_size(db: Path) -> int:
    """Bytes the snapshot can need: the database plus its write-ahead log."""
    wal = db.with_name(db.name + "-wal")
    return db.stat().st_size + (wal.stat().st_size if wal.exists() else 0)


def check_integrity(path: Path, quick: bool) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        pragma = "quick_check" if quick else "integrity_check"
        rows = conn.execute(f"PRAGMA {pragma}").fetchall()
    finally:
        conn.close()
    result = "; ".join(str(r[0]) for r in rows[:5])
    return result


def table_counts(path: Path) -> Dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {n: conn.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


def snapshot(src: Path, dest: Path) -> None:
    """Write a consistent copy of ``src`` to ``dest`` without writing to ``src``."""
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        if sqlite3.sqlite_version_info >= (3, 27, 0):
            conn.execute("VACUUM INTO ?", (str(dest),))
        else:  # pragma: no cover - SQLite before VACUUM INTO (2019)
            out = sqlite3.connect(str(dest))
            try:
                conn.backup(out)
            finally:
                out.close()
    finally:
        conn.close()


def backup_name(src: Path, dbs: List[Path], data_root: Path) -> str:
    """The file name inside the backup: the base name (what the restore
    runbook expects), or, when two databases share it, the path relative to
    the data root with "/" turned into "-" (detections/users.db ->
    detections-users.db)."""
    if sum(1 for d in dbs if d.name == src.name) == 1:
        return src.name
    try:
        rel = src.resolve().relative_to(data_root.resolve())
    except ValueError:
        rel = Path(src.parent.name) / src.name
    return str(rel).replace(os.sep, "-")


def chown_like(paths: List[Path], reference: Path) -> None:
    if os.geteuid() != 0:
        return
    st = reference.stat()
    for p in paths:
        os.chown(p, st.st_uid, st.st_gid)


def backup(args: argparse.Namespace) -> int:
    data_root: Path = args.data_root
    dest: Path = args.dest or data_root / "backups" / dt.datetime.now().strftime("%Y%m%d-%H%M")
    dbs = [Path(p) for p in args.db] if args.db else find_databases(data_root)
    if not dbs:
        log(f"ERROR: no databases found under {data_root}")
        return 1

    empty = [d for d in dbs if d.stat().st_size == 0]
    dbs = [d for d in dbs if d.stat().st_size > 0]
    configs = [args.config_dir / n for n in CONFIG_FILES if (args.config_dir / n).is_file()]

    need = int(sum(live_size(d) for d in dbs) * FREE_SPACE_MARGIN)
    probe = dest
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free

    log(f"Backup destination: {dest}")
    for d in dbs:
        log(f"  database  {d}  ({live_size(d) / 1e6:.1f} MB incl. WAL)")
    for d in empty:
        log(f"  skipped   {d}  (empty file)")
    for c in configs:
        log(f"  config    {c}")
    log(f"  needs about {need / 1e9:.2f} GB; {free / 1e9:.1f} GB free on {probe}")

    # An existing directory is fine (the rollout runbook captures unit state
    # into the same one first) as long as nothing in it would be overwritten.
    if dest.exists():
        planned = ["SHA256SUMS", "manifest.json"] + [backup_name(d, dbs, data_root) for d in dbs]
        planned += [c.name for c in configs]
        clash = sorted(n for n in planned if (dest / n).exists() or (dest / (n + ".partial")).exists())
        if not dest.is_dir() or clash:
            log(f"ERROR: {dest} already holds {', '.join(clash) or 'a non-directory'}; refusing to mix backups")
            return 1
    if need > free:
        log("ERROR: not enough free space; nothing was written")
        return 1
    if args.dry_run:
        log("dry run: nothing was written")
        return 0

    written: List[Path] = []
    if not dest.exists():
        dest.mkdir(parents=True)
        os.chmod(dest, 0o750)
        written.append(dest)
    manifest = {
        "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "sqlite_version": sqlite3.sqlite_version,
        "check": "quick_check" if args.quick else "integrity_check",
        "databases": {},
        "configs": [],
        "skipped_empty": [str(d) for d in empty],
    }
    sums: List[str] = []
    failed = False

    for src in dbs:
        name = backup_name(src, dbs, data_root)
        final = dest / name
        partial = dest / (name + ".partial")
        log(f"→ {src}")
        try:
            snapshot(src, partial)
            check = check_integrity(partial, args.quick)
        except sqlite3.Error as exc:
            log(f"  ❌ snapshot failed: {exc}")
            failed = True
            continue
        if check != "ok":
            log(f"  ❌ {manifest['check']} on the copy: {check}")
            failed = True
            continue
        partial.rename(final)
        digest = sha256(final)
        counts = table_counts(final)
        manifest["databases"][name] = {
            "source": str(src),
            "bytes": final.stat().st_size,
            "sha256": digest,
            "tables": counts,
        }
        sums.append(f"{digest}  {name}")
        written.append(final)
        rows = sum(counts.values())
        log(f"  ✅ {final.stat().st_size / 1e6:.1f} MB, {len(counts)} tables, {rows} rows, {manifest['check']} ok")

    for cfg in configs:
        target = dest / cfg.name
        shutil.copy2(cfg, target)  # keeps .env's restrictive mode
        digest = sha256(target)
        sums.append(f"{digest}  {cfg.name}")
        manifest["configs"].append({"source": str(cfg), "name": cfg.name, "sha256": digest})
        written.append(target)
        log(f"  ✅ copied {cfg}")

    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    written += [dest / "SHA256SUMS", dest / "manifest.json"]
    chown_like(written, data_root)

    if failed:
        log(f"❌ backup INCOMPLETE in {dest}: see the failures above")
        return 1
    log(f"✅ backup complete: {dest}")
    log(f"   check it any time with: python3 {sys.argv[0]} --verify {dest}")
    return 0


def verify(dest: Path, quick: bool) -> int:
    sums_file = dest / "SHA256SUMS"
    if not sums_file.is_file():
        log(f"ERROR: {sums_file} not found; is {dest} a backup made by this tool?")
        return 1
    failed = False
    for line in sums_file.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip()
        path = dest / name
        if not path.is_file():
            log(f"❌ {name}: missing")
            failed = True
            continue
        if sha256(path) != digest:
            log(f"❌ {name}: sha256 mismatch (the file changed after the backup)")
            failed = True
            continue
        if name.endswith(".db"):
            try:
                check = check_integrity(path, quick)
            except sqlite3.Error as exc:
                check = str(exc)
            if check != "ok":
                log(f"❌ {name}: {check}")
                failed = True
                continue
        log(f"✅ {name}")
    leftovers = sorted(p.name for p in dest.glob("*.partial"))
    if leftovers:
        log(f"❌ unfinished snapshots present: {', '.join(leftovers)}")
        failed = True
    log("❌ backup FAILED verification" if failed else f"✅ {dest} verified")
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--dest", type=Path, help="backup directory (default <data-root>/backups/YYYYmmdd-HHMM)")
    parser.add_argument("--db", action="append", default=[], help="back up only this database (repeatable)")
    parser.add_argument("--quick", action="store_true", help="quick_check instead of the full integrity_check")
    parser.add_argument("--dry-run", action="store_true", help="show what would be backed up, write nothing")
    parser.add_argument("--verify", type=Path, metavar="DIR", help="re-check an existing backup and exit")
    args = parser.parse_args(argv)
    if args.verify:
        return verify(args.verify, args.quick)
    return backup(args)


if __name__ == "__main__":
    sys.exit(main())
