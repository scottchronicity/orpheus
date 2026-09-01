"""The one component that deletes recordings.

Every agent used to trim its own directory, which produced four independent
answers to a question the disk only asks once. Each agent honored a budget
scoped to its own files and knew nothing about the shared filesystem, so a
station could sit comfortably inside four budgets while filling up — and the
directories no agent owned (timelapses above all) grew without limit, because
a per-agent cleanup can only ever cover the agents that exist.

So: one sweep, run from a timer, owning every category. It enforces two
different things and keeps them apart, because they answer different
questions:

* **Ceilings** cap how much any one kind of recording may hold. They apply
  whether or not the disk is under pressure — a category over its ceiling is
  over budget even on an empty drive.
* **Pressure** is the shared filesystem running low. When free space falls
  under the reserve, every category above its floor gives up data in
  proportion to how much it has to give, so one category does not lose
  everything while another sits untouched.

Underneath both is a **floor**: a stretch of recent recording that is never
deleted for any reason. If holding the floor means missing a ceiling, or
means failing to reach the reserve, the sweep logs and stops. Deleting the
last month of audio to satisfy a number in a config file is the worse
outcome, and it is not reversible.

Nothing here runs as a daemon. A sweep is a measurement and a decision; it
holds no state between runs beyond a report on disk, so there is nothing to
supervise and nothing to leak. See ``docs/designs/storage-retention.md``.
"""

from __future__ import annotations

import csv
import errno
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from orpheus_common.logging import get_logger
from orpheus_common.storage.cleanup import DiskSpace, read_disk_space
from orpheus_common.storage.usage import DATA_ROOT_CATEGORIES, survey_data_root

logger = get_logger(__name__)

BYTES_PER_GIB = 1024**3

# How much one category gives up per pressure round. Small enough that the
# sweep re-reads the disk often (other things are writing to it while this
# runs), large enough that recovering tens of gigabytes does not take
# thousands of rounds.
PRESSURE_CHUNK_BYTES = 512 * 1024**2

# A last backstop against a round loop that never converges. At 512 MB per
# category per round it bounds one sweep well above any real recovery — which
# also means it is far too loose to be the thing that protects the archive.
# MAX_STALLED_ROUNDS below is what actually stops a runaway; this only catches
# a loop that is somehow still making progress after thousands of rounds.
MAX_PRESSURE_ROUNDS = 4096

# How many consecutive rounds may delete recordings without the data root's
# free space responding before the sweep gives up. Deleting real bytes and
# seeing free space stay flat means the deletions are not solving the problem:
# something is refilling the disk as fast as the sweep empties it, a category
# is on a different filesystem, or unlinked files are still held open. In all
# three the loop would otherwise continue until every pool was empty, deleting
# the entire history above every floor to chase a number it can never reach.
# Three rounds costs at most a few GiB before stopping.
MAX_STALLED_ROUNDS = 3

# How much of what a round deleted must show up as free space for the round to
# count as progress. Not 1.0: other things write to the disk while the sweep
# runs, so exact agreement never happens. Well above 0, because the failure
# this catches shows up as free space barely moving at all.
PROGRESS_FRACTION = 0.5

# The report the dashboard reads, the lock a hand-run takes, and the
# manifests of what was removed. All under the data root, so they travel with
# the data rather than with the deployment.
STATE_FILENAME = ".storage-sweep-state.json"
LOCK_FILENAME = ".storage-sweep.lock"
MANIFEST_DIRNAME = ".storage-sweep-manifests"

# Manifests are the record of what disappeared, so they are worth keeping —
# but a retention component that grows a directory without limit would be
# embarrassing. Recent history is what anyone actually reads.
MANIFEST_KEEP = 50

_CATEGORY_PATHS: dict[str, str] = {c.key: c.relative_path for c in DATA_ROOT_CATEGORIES}


@dataclass
class SweepFile:
    """One deletable file: where it is, how big, and how old."""

    path: Path
    size_bytes: int
    mtime: float


@dataclass
class CategoryOutcome:
    """What the sweep did to one category, and what stopped it."""

    key: str
    path: Path
    max_bytes: int
    floor_days: int
    bytes_before: int
    file_count_before: int
    files_removed: int = 0
    bytes_freed: int = 0
    oldest_removed: Optional[str] = None
    newest_removed: Optional[str] = None
    # Over its ceiling when the sweep started. Kept separately from
    # "still over now", so the report can say the sweep acted.
    over_ceiling: bool = False
    # The sweep wanted to delete more and the floor refused. This is the
    # signal that a ceiling and a floor have been configured to contradict
    # each other, or that the disk cannot be recovered without data loss
    # the operator has not agreed to.
    floor_blocked: bool = False

    @property
    def bytes_after(self) -> int:
        return max(self.bytes_before - self.bytes_freed, 0)

    @property
    def percent_of_limit(self) -> float:
        if self.max_bytes <= 0:
            return 0.0
        return self.bytes_after / self.max_bytes * 100

    def note_removed(self, files: list[SweepFile]) -> None:
        """Widen the window of recording this sweep removed.

        Accumulated across both phases, so a category trimmed for its ceiling
        and again under pressure reports one window rather than the last one.
        """
        if not files:
            return
        stamps = [datetime.fromtimestamp(f.mtime).astimezone() for f in files]
        oldest = min(stamps).isoformat()
        newest = max(stamps).isoformat()
        self.oldest_removed = min([s for s in (self.oldest_removed, oldest) if s])
        self.newest_removed = max([s for s in (self.newest_removed, newest) if s])

    def to_dict(self, *, simulated: bool = False) -> dict[str, Any]:
        """The per-category block of the published report.

        ``simulated`` is true for a sweep that decided everything a real one
        would and deleted nothing — a dry run, the first-run grace, or
        ``sweep_enabled: false``. The counts are then a forecast, and they are
        published under ``would_remove`` rather than ``last_sweep`` so that a
        consumer which only knows ``last_sweep`` shows nothing at all instead
        of showing a forecast as history. The dashboard spent the whole grace
        window telling the operator that recordings had been deleted while the
        banner above it said none had.

        The byte figures follow the same rule: nothing was freed, so the
        category still holds what it held.
        """
        bytes_now = self.bytes_before if simulated else self.bytes_after
        percent = (bytes_now / self.max_bytes * 100) if self.max_bytes > 0 else 0.0
        window = (
            {
                "files_removed": self.files_removed,
                "bytes_freed": self.bytes_freed,
                "oldest_removed": self.oldest_removed,
                "newest_removed": self.newest_removed,
            }
            if self.files_removed
            else None
        )
        return {
            "path": str(self.path),
            "limit_bytes": self.max_bytes,
            "bytes": bytes_now,
            "percent_of_limit": round(percent, 1),
            # The ceiling *is* the trigger: there is no separate "start
            # worrying at 90%" threshold, because the sweep runs every few
            # minutes rather than every few hours and has no need to act early.
            "trigger_percent": 100.0,
            "floor_days": self.floor_days,
            "over_ceiling": self.over_ceiling,
            "floor_blocked": self.floor_blocked,
            "last_sweep": None if simulated else window,
            "would_remove": window if simulated else None,
        }


@dataclass
class SweepResult:
    """Everything one sweep decided, did, and could not do."""

    report: dict[str, Any] = field(default_factory=dict)
    outcomes: list[CategoryOutcome] = field(default_factory=list)
    files_removed: int = 0
    bytes_freed: int = 0
    manifest_path: Optional[Path] = None
    # Free space is under the reserve and every category is at its floor.
    # The one condition the sweep cannot fix by itself.
    blocked_under_reserve: bool = False
    errors: list[str] = field(default_factory=list)


def scan_category(path: Path) -> list[SweepFile]:
    """Every file under ``path``, with size and mtime, oldest first.

    Separate from :func:`orpheus_common.storage.usage.measure_directory`
    because that one answers "how big" and throws the per-file detail away.
    Eviction needs the detail, so this keeps it — but only for the categories
    a sweep actually has to act on, which on a healthy station is none of
    them.
    """
    files: list[SweepFile] = []
    if not path.exists():
        return files

    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            files.append(
                                SweepFile(
                                    path=Path(entry.path),
                                    size_bytes=stat.st_size,
                                    mtime=stat.st_mtime,
                                )
                            )
                    except OSError:
                        # Vanished between listing and stat, or unreadable.
                        continue
        except OSError:
            continue

    files.sort(key=lambda f: f.mtime)
    return files


class StorageSweep:
    """Enforce every retention rule on the data root, in one pass.

    ``disk_space``, ``now``, ``scan`` and ``remove`` are all injectable so the
    whole decision surface — a nearly-full disk, a floor that blocks eviction,
    a category over its ceiling — can be exercised in tests without filling a
    real filesystem or deleting a real recording.
    """

    def __init__(
        self,
        root: Path,
        retention: Any,
        *,
        disk_space: Optional[Callable[[Path], Optional[DiskSpace]]] = None,
        now: Optional[Callable[[], datetime]] = None,
        scan: Optional[Callable[[Path], list[SweepFile]]] = None,
        remove: Optional[Callable[[Path], None]] = None,
    ) -> None:
        self.root = Path(root)
        self.retention = retention
        self._disk_space = disk_space or read_disk_space
        self._now = now or (lambda: datetime.now().astimezone())
        self._scan = scan or scan_category
        self._remove = remove or (lambda p: p.unlink())
        self._scanned: dict[str, list[SweepFile]] = {}
        # Paths this sweep has already accounted for. Ceilings and pressure
        # both draw from the same scanned list, so without this the second
        # phase would re-select a file the first phase deleted and count its
        # bytes twice.
        self._deleted: set[Path] = set()

    # -- thresholds ------------------------------------------------------

    def effective_reserve_bytes(self, space: Optional[DiskSpace]) -> int:
        """Free space the sweep works to keep, in bytes.

        ``reserve_gb`` and the older ``min_free_space_percent`` both describe
        the same threshold in different units, and stations upgrading from the
        per-agent arrangement have the percentage set. Rather than pick a
        winner by config precedence — which would silently loosen the guard on
        one of the two — the stricter of the two applies.
        """
        reserve = int(self.retention.reserve_gb * BYTES_PER_GIB)
        percent = getattr(self.retention, "min_free_space_percent", 0.0) or 0.0
        if space is not None and space.total_bytes > 0 and percent > 0:
            reserve = max(reserve, int(space.total_bytes * percent / 100))
        return reserve

    def _cutoffs(self, floor_days: int) -> tuple[float, float]:
        """The two epoch timestamps a file must predate to be deletable.

        The floor is the operator's promise about recent recording; the
        minimum file age protects a clip that is still being written. Both are
        hard, and the sweep never deletes a file newer than either.
        """
        now = self._now()
        floor = (now - timedelta(days=floor_days)).timestamp()
        min_age = (
            now - timedelta(hours=float(getattr(self.retention, "min_file_age_hours", 1.0)))
        ).timestamp()
        return floor, min_age

    def _files_for(self, key: str, path: Path) -> list[SweepFile]:
        if key not in self._scanned:
            self._scanned[key] = self._scan(path)
        return self._scanned[key]

    def _evictable(self, files: list[SweepFile], floor_days: int) -> list[SweepFile]:
        """Files old enough to delete, oldest first.

        A file must clear *both* cutoffs, so the effective boundary is the
        earlier of the two — whichever protects more.
        """
        floor, min_age = self._cutoffs(floor_days)
        cutoff = min(floor, min_age)
        return [f for f in files if f.mtime < cutoff and f.path not in self._deleted]

    # -- eviction --------------------------------------------------------

    def _evict(
        self,
        outcome: CategoryOutcome,
        files: list[SweepFile],
        target_bytes: int,
        *,
        dry_run: bool,
        removed: list[SweepFile],
    ) -> int:
        """Delete oldest-first from ``files`` until ``target_bytes`` is freed.

        Always oldest-first, whatever the category: the predictable thing to
        lose is the oldest recording. Selecting the largest files would free
        space faster and leave an operator unable to say what window of
        history they still have.

        ``files`` is mutated — entries that go away are dropped from the list,
        so a later pressure round does not try to delete them twice.
        """
        freed = 0
        gone: list[SweepFile] = []
        took: list[SweepFile] = []

        for candidate in files:
            if freed >= target_bytes:
                break
            try:
                if not dry_run:
                    self._remove(candidate.path)
            except FileNotFoundError:
                # Already gone — a recording that rolled over mid-sweep. Drop
                # it from the pool but do not claim its bytes as freed.
                gone.append(candidate)
                continue
            except OSError as exc:
                logger.warning(
                    "Could not remove file",
                    path=str(candidate.path),
                    category=outcome.key,
                    error=str(exc),
                )
                continue

            gone.append(candidate)
            took.append(candidate)
            removed.append(candidate)
            freed += candidate.size_bytes
            outcome.files_removed += 1
            outcome.bytes_freed += candidate.size_bytes

        outcome.note_removed(took)
        for candidate in gone:
            self._deleted.add(candidate.path)
            files.remove(candidate)
        return freed

    # -- the sweep -------------------------------------------------------

    def _contained(self, path: Path, root_resolved: Path, key: str) -> bool:
        """Whether a category directory really lives under the data root.

        The category paths are hardcoded and the keys are whitelisted, so this
        cannot be reached by editing config. It can be reached with a symlink
        or a mount: an operator who moves timelapses onto a second drive and
        symlinks the old location back has, without touching Orpheus at all,
        pointed the deleter at a filesystem the sweep does not manage. Deleting
        there also never returns space to the disk that was full, so pressure
        relief would keep taking from it round after round.

        A category that has escaped is skipped whole — not swept, not
        measured against its ceiling, and loud about it. Refusing to delete is
        the only safe response to not knowing where you are.
        """
        if not path.exists():
            # Nothing to contain yet. A missing directory is a no-op elsewhere.
            return True
        try:
            resolved = path.resolve()
        except OSError as exc:
            logger.error(
                "Could not resolve a storage category — skipping it entirely",
                category=key,
                path=str(path),
                error=str(exc),
            )
            return False
        if resolved != root_resolved and root_resolved not in resolved.parents:
            logger.critical(
                "Storage category resolves outside the data root — skipping it "
                "entirely. Nothing in it will be measured or deleted. A symlink or "
                "a mount points this category at another filesystem; deleting there "
                "would not free space on the data root, so the sweep refuses.",
                category=key,
                path=str(path),
                resolves_to=str(resolved),
                data_root=str(root_resolved),
            )
            return False
        return True

    def run(self, *, dry_run: bool = False) -> SweepResult:
        """Measure, enforce ceilings, relieve pressure, and report.

        ``dry_run`` decides everything exactly as a real sweep would and
        removes nothing, which is what ``make storage-report`` runs and what
        the first sweep after an install does on its own.
        """
        result = SweepResult()
        started_at = self._now()
        survey = survey_data_root(self.root, disk_space=self._disk_space)
        space = self._disk_space(self.root)
        reserve = self.effective_reserve_bytes(space)

        outcomes: dict[str, CategoryOutcome] = {}
        root_resolved = self.root.resolve()
        for key, rule in self.retention.categories.items():
            measured = (survey.get("categories") or {}).get(key) or {}
            path = self.root / _CATEGORY_PATHS.get(key, key)
            if not self._contained(path, root_resolved, key):
                continue
            max_bytes = int(rule.max_gb * BYTES_PER_GIB)
            bytes_before = int(measured.get("bytes") or 0)
            outcomes[key] = CategoryOutcome(
                key=key,
                path=path,
                max_bytes=max_bytes,
                floor_days=rule.floor_days,
                bytes_before=bytes_before,
                file_count_before=int(measured.get("file_count") or 0),
                over_ceiling=bytes_before > max_bytes,
            )

        removed: list[SweepFile] = []

        self._enforce_ceilings(outcomes, dry_run=dry_run, removed=removed)
        free_after = self._relieve_pressure(
            outcomes, space, reserve, result, dry_run=dry_run, removed=removed
        )

        result.outcomes = list(outcomes.values())
        result.files_removed = sum(o.files_removed for o in result.outcomes)
        result.bytes_freed = sum(o.bytes_freed for o in result.outcomes)

        if removed and not dry_run:
            result.manifest_path = self._write_manifest(removed, started_at)
            # Re-measure so the dashboard shows what is on the disk now, not
            # what was there before this sweep ran. Deliberately into new
            # names: `space` is the before reading, and the report states
            # both, which is how an operator sees what the sweep bought.
            survey = survey_data_root(self.root, disk_space=self._disk_space)
            reread = self._disk_space(self.root)
            if reread is not None:
                free_after = reread.free_bytes

        result.report = self._build_report(
            survey=survey,
            space=space,
            reserve=reserve,
            free_after=free_after,
            outcomes=outcomes,
            result=result,
            started_at=started_at,
            dry_run=dry_run,
        )
        return result

    def _enforce_ceilings(
        self,
        outcomes: dict[str, CategoryOutcome],
        *,
        dry_run: bool,
        removed: list[SweepFile],
    ) -> None:
        """Bring every category back under its ceiling, floors permitting.

        This runs regardless of free space. A ceiling is a statement about how
        much of one kind of recording the station keeps, and it is just as
        true on a drive with a terabyte spare.
        """
        for outcome in outcomes.values():
            if outcome.bytes_before <= outcome.max_bytes:
                continue

            over_by = outcome.bytes_before - outcome.max_bytes
            files = self._files_for(outcome.key, outcome.path)
            evictable = self._evictable(files, outcome.floor_days)
            available = sum(f.size_bytes for f in evictable)

            logger.warning(
                "Category over its ceiling",
                category=outcome.key,
                path=str(outcome.path),
                bytes=outcome.bytes_before,
                gib=round(outcome.bytes_before / BYTES_PER_GIB, 2),
                limit_gib=round(outcome.max_bytes / BYTES_PER_GIB, 2),
                over_by_gib=round(over_by / BYTES_PER_GIB, 2),
                floor_days=outcome.floor_days,
                evictable_gib=round(available / BYTES_PER_GIB, 2),
                dry_run=dry_run,
            )

            freed = self._evict(outcome, evictable, over_by, dry_run=dry_run, removed=removed)

            if freed < over_by:
                outcome.floor_blocked = True
                logger.critical(
                    "Cannot reach ceiling without breaching the floor — stopping. "
                    "Everything still held is inside the retention floor. Raise the "
                    "ceiling or lower the floor for this category; the sweep will not "
                    "delete recent recordings to satisfy a size budget.",
                    category=outcome.key,
                    path=str(outcome.path),
                    floor_days=outcome.floor_days,
                    limit_gib=round(outcome.max_bytes / BYTES_PER_GIB, 2),
                    still_over_gib=round((over_by - freed) / BYTES_PER_GIB, 2),
                )

    def _relieve_pressure(
        self,
        outcomes: dict[str, CategoryOutcome],
        space: Optional[DiskSpace],
        reserve: int,
        result: SweepResult,
        *,
        dry_run: bool,
        removed: list[SweepFile],
    ) -> Optional[int]:
        """Free space until the reserve is met, taking proportionally.

        Every category above its floor contributes in proportion to how much
        it has to give. Taking a fixed share each would empty a small category
        entirely while a large one barely noticed; taking it all from the
        largest would make one kind of recording carry the whole cost of a
        disk that every kind is filling.

        Returns free bytes at the end, or ``None`` if the disk is unreadable.
        """
        if space is None:
            logger.warning(
                "Could not read free space — enforced ceilings only, skipped pressure relief",
                path=str(self.root),
            )
            return None

        free_bytes = space.free_bytes
        if free_bytes >= reserve:
            return free_bytes

        logger.warning(
            "Free space below the reserve — relieving pressure across categories",
            free_gib=round(free_bytes / BYTES_PER_GIB, 2),
            reserve_gib=round(reserve / BYTES_PER_GIB, 2),
            shortfall_gib=round((reserve - free_bytes) / BYTES_PER_GIB, 2),
            dry_run=dry_run,
        )

        pools: dict[str, list[SweepFile]] = {}
        for key, outcome in outcomes.items():
            files = self._files_for(key, outcome.path)
            pools[key] = self._evictable(files, outcome.floor_days)

        stalled_rounds = 0
        for round_index in range(MAX_PRESSURE_ROUNDS):
            if free_bytes >= reserve:
                break

            eligible = [k for k, pool in pools.items() if pool]
            if not eligible:
                result.blocked_under_reserve = True
                for outcome in outcomes.values():
                    # Only categories that actually held something back. A
                    # category with nothing in it did not refuse to give — and
                    # the panel renders floor_blocked as "over its ceiling, but
                    # everything it holds is inside the floor", which about an
                    # empty directory is simply false. That sentence is read by
                    # an operator deciding whether to lower floor_days, which is
                    # the one action here that loses recordings for good.
                    if outcome.bytes_before > 0:
                        outcome.floor_blocked = True
                logger.critical(
                    "Free space is below the reserve and every category is at its "
                    "retention floor. The sweep will not delete inside a floor, so it "
                    "is stopping with the disk still short. Lower storage.retention "
                    "floor_days, lower reserve_gb, or add capacity.",
                    free_gib=round(free_bytes / BYTES_PER_GIB, 2),
                    reserve_gib=round(reserve / BYTES_PER_GIB, 2),
                    shortfall_gib=round((reserve - free_bytes) / BYTES_PER_GIB, 2),
                )
                break

            total_evictable = sum(sum(f.size_bytes for f in pools[k]) for k in eligible)
            if total_evictable <= 0:
                # Eligible files that occupy no space. Nothing here can move
                # the disk, and the reserve is still unmet.
                result.blocked_under_reserve = True
                logger.critical(
                    "Free space is below the reserve and the only files outside the "
                    "floors are empty. The sweep cannot recover this disk; something "
                    "other than recordings is using the space.",
                    free_gib=round(free_bytes / BYTES_PER_GIB, 2),
                    reserve_gib=round(reserve / BYTES_PER_GIB, 2),
                )
                break

            round_total = PRESSURE_CHUNK_BYTES * len(eligible)
            freed_this_round = 0
            for key in eligible:
                pool_bytes = sum(f.size_bytes for f in pools[key])
                share = int(round_total * pool_bytes / total_evictable)
                freed_this_round += self._evict(
                    outcomes[key], pools[key], share, dry_run=dry_run, removed=removed
                )

            if freed_this_round <= 0:
                # Nothing moved despite eligible files — deletions are failing.
                # Spinning would turn that into a hung timer unit.
                result.blocked_under_reserve = True
                logger.critical(
                    "Free space is below the reserve and every deletion this round "
                    "failed. Retention is not working on this station — check "
                    "ownership and permissions under the data root.",
                    round=round_index,
                    free_gib=round(free_bytes / BYTES_PER_GIB, 2),
                    reserve_gib=round(reserve / BYTES_PER_GIB, 2),
                )
                break

            before_round = free_bytes
            if dry_run:
                free_bytes += freed_this_round
            else:
                current = self._disk_space(self.root)
                free_bytes = current.free_bytes if current else free_bytes + freed_this_round

            # Is the disk answering? A round can delete real bytes and move the
            # free-space number barely at all: a category living on another
            # filesystem, a runaway writer refilling as fast as the sweep
            # frees, files unlinked but still held open. Without this check the
            # loop's only stopping condition is an empty pool, so it would work
            # through every recording above every floor — years of history — in
            # a single sweep, while never reaching the reserve. The design says
            # this sweep takes a bounded chunk per round; that only bounds the
            # damage if the rounds themselves are bounded.
            if not dry_run:
                gained = free_bytes - before_round
                if gained < freed_this_round * PROGRESS_FRACTION:
                    stalled_rounds += 1
                else:
                    stalled_rounds = 0
                if stalled_rounds >= MAX_STALLED_ROUNDS:
                    result.blocked_under_reserve = True
                    logger.critical(
                        "Deleting recordings is not returning free space to the data "
                        "root, so the sweep is stopping rather than working through "
                        "the rest of the history. Something else is consuming the "
                        "space as fast as it is freed, a category is on a different "
                        "filesystem, or deleted files are still held open.",
                        rounds=stalled_rounds,
                        freed_gib=round(result.bytes_freed / BYTES_PER_GIB, 2),
                        free_gib=round(free_bytes / BYTES_PER_GIB, 2),
                        reserve_gib=round(reserve / BYTES_PER_GIB, 2),
                    )
                    break
        else:
            result.blocked_under_reserve = True
            logger.critical(
                "Pressure relief hit the round limit without reaching the reserve",
                rounds=MAX_PRESSURE_ROUNDS,
                free_gib=round(free_bytes / BYTES_PER_GIB, 2),
                reserve_gib=round(reserve / BYTES_PER_GIB, 2),
            )

        return free_bytes

    # -- reporting -------------------------------------------------------

    def _write_manifest(self, removed: list[SweepFile], started_at: datetime) -> Optional[Path]:
        """A CSV of exactly what disappeared, so it can be reconstructed later.

        Written after the deletions rather than before: a manifest listing
        files that were never removed is worse than no manifest, because it
        reads as an inventory of loss that did not happen.
        """
        manifest_dir = self.root / MANIFEST_DIRNAME
        try:
            manifest_dir.mkdir(parents=True, exist_ok=True)
            path = manifest_dir / f"sweep_{started_at.strftime('%Y%m%d_%H%M%S')}.csv"
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["path", "size_bytes", "mtime"])
                for item in removed:
                    writer.writerow(
                        [
                            str(item.path),
                            item.size_bytes,
                            datetime.fromtimestamp(item.mtime).astimezone().isoformat(),
                        ]
                    )
        except OSError as exc:
            logger.warning("Could not write deletion manifest", error=str(exc))
            return None

        try:
            existing = sorted(manifest_dir.glob("sweep_*.csv"))
            for stale in existing[:-MANIFEST_KEEP]:
                stale.unlink()
        except OSError:
            pass

        return path

    def _build_report(
        self,
        *,
        survey: dict[str, Any],
        space: Optional[DiskSpace],
        reserve: int,
        free_after: Optional[int],
        outcomes: dict[str, CategoryOutcome],
        result: SweepResult,
        started_at: datetime,
        dry_run: bool,
    ) -> dict[str, Any]:
        """The published record of this sweep.

        This is what the Diagnostics storage panel renders. The sweep is the
        component that walked the directories and holds the policy, so it is
        the only honest source for "how close is this to being deleted" — a
        dashboard asking the same question for itself would duplicate a walk
        over a quarter-million files and become a second, disagreeing answer.
        """
        free_bytes = free_after if free_after is not None else (space.free_bytes if space else None)
        return {
            "swept_at": started_at.isoformat(),
            "data_root": str(self.root),
            "dry_run": dry_run,
            "sweep_interval_minutes": float(
                getattr(self.retention, "sweep_interval_minutes", 15.0)
            ),
            "reserve_bytes": reserve,
            "free_bytes_before": space.free_bytes if space else None,
            "free_bytes_after": free_bytes,
            # True when the disk is under the reserve right now, whether or
            # not this sweep could do anything about it.
            "guard_tripped": free_bytes is not None and free_bytes < reserve,
            # True only when it is under the reserve AND nothing may be
            # deleted — the condition an operator has to resolve by hand.
            "blocked_under_reserve": result.blocked_under_reserve,
            "files_removed": result.files_removed,
            "bytes_freed": result.bytes_freed,
            "manifest_path": str(result.manifest_path) if result.manifest_path else None,
            "categories": {
                key: outcome.to_dict(simulated=dry_run) for key, outcome in outcomes.items()
            },
            "survey": survey,
        }


# -- state file ----------------------------------------------------------
#
# The sweep is a one-shot with no bus connection: connecting to a broker to
# announce a measurement, then exiting, would make a component that deletes
# files depend on a component that delivers messages. The report lands on the
# data root instead, next to the data it describes, and whoever wants it
# reads it there.


def state_path(root: Path) -> Path:
    return Path(root) / STATE_FILENAME


def read_state(root: Path) -> Optional[dict[str, Any]]:
    """The last sweep's report, or ``None`` if there is not one to read."""
    path = state_path(root)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_state(root: Path, report: dict[str, Any]) -> Optional[Path]:
    """Publish ``report`` atomically.

    Written to a temporary file and renamed, so a reader mid-sweep sees the
    previous report in full rather than half of the next one.
    """
    path = state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".sweep-state-", delete=False
        )
        with handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        os.replace(handle.name, path)
        os.chmod(path, 0o644)
    except OSError as exc:
        logger.warning("Could not publish sweep report", path=str(path), error=str(exc))
        return None
    return path


# -- the command ---------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1
# Free space is under the reserve and the floors will not yield. The unit
# ends up failed on purpose: this is the one storage condition an operator
# has to resolve by hand, and a green timer would hide it.
EXIT_BLOCKED = 2

REVIEW_COMMAND = "make storage-report"


_LOCK_UNSUPPORTED = object()
"""No POSIX advisory locks on this platform. Truthy, so the sweep proceeds."""


def _acquire_lock(root: Path):
    """Take the sweep lock, or return ``None`` if another sweep holds it.

    Two sweeps deleting from the same directory would both plan against a
    filesystem the other is changing underneath them, and between them free
    far more than either intended. The timer alone would not collide, but a
    hand-run during a scheduled sweep would.

    Contention is the ONLY condition that returns ``None``. Every other way
    the lock can fail — the data root unwritable by ``orpheus``, the drive
    not mounted so the bare mountpoint is root-owned, a read-only remount, a
    lock file left behind by another user — raises, because the caller turns
    ``None`` into a clean exit. A sweep that cannot lock is a sweep that is
    not running, and on a station where nothing else deletes recordings that
    has to fail loudly rather than report success every fifteen minutes while
    the disk fills.

    The lock file is left behind on purpose and stays 0 bytes: the lock lives
    on the open file description, not on the file existing, so unlinking it
    would let the next sweep lock a fresh inode while another process still
    held the old one. Nothing can go stale — flock is released by the kernel
    when the holder's descriptors close, which happens however the process
    dies, SIGKILL and the unit's TimeoutStartSec included. A killed sweep
    therefore costs one tick, not retention itself.
    """
    try:
        import fcntl  # noqa: PLC0415
    except ImportError:
        # No POSIX advisory locks (Windows checkout). The command is only
        # ever scheduled on the station; running unlocked beats not running.
        return _LOCK_UNSUPPORTED

    path = Path(root) / LOCK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")  # noqa: SIM115 — held for the process lifetime
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            return None
        raise
    return handle


def _grace_state(
    retention: Any, state: Optional[dict[str, Any]], now: datetime
) -> tuple[bool, str]:
    """Whether the first-run grace is still in effect, and since when.

    A fresh install gets one window in which the sweep says what it would
    delete without deleting it. An operator who disagrees with the ceilings
    finds out before the recordings are gone rather than after, which is the
    only order that matters for something irreversible.

    ``--force`` ends the window for good rather than for one run: an operator
    who has read the report and started enforcement should not find the timer
    quietly back in report-only mode on its next tick.
    """
    grace_hours = float(getattr(retention, "first_run_grace_hours", 24.0))
    if (state or {}).get("grace_ended"):
        return False, str((state or {}).get("installed_at") or now.isoformat())

    installed_raw = (state or {}).get("installed_at")

    installed_at: Optional[datetime] = None
    if isinstance(installed_raw, str):
        try:
            installed_at = datetime.fromisoformat(installed_raw)
        except ValueError:
            installed_at = None

    if installed_at is None:
        return grace_hours > 0, now.isoformat()

    if grace_hours <= 0:
        return False, installed_at.isoformat()

    return now - installed_at < timedelta(hours=grace_hours), installed_at.isoformat()


def _logs_to_stderr() -> None:
    """Move every stream log handler off stdout.

    ``setup_logging`` writes to stdout, which is right for a service under
    journald and wrong for a command whose stdout a caller is parsing.
    """
    import logging  # noqa: PLC0415
    import sys  # noqa: PLC0415

    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.setStream(sys.stderr)


def _format_summary(report: dict[str, Any]) -> str:
    """The operator-facing view of one sweep, for ``make storage-report``."""

    def gib(value: Optional[int]) -> str:
        return "—" if value is None else f"{value / BYTES_PER_GIB:,.1f} GiB"

    lines = [f"Data root: {report['data_root']}"]
    if not report.get("sweep_enabled", True):
        mode = "disabled — storage.retention.sweep_enabled is false"
    elif report.get("report_only"):
        # Both facts matter here and neither implies the other: the operator
        # asked for a dry run, and separately, enforcement has not started.
        mode = "dry run — and the first-run grace is still in effect"
    else:
        mode = "dry run — enforcement is active, so a real sweep would do this"
    lines.append(f"Mode:      {mode}")
    lines.append(
        f"Free:      {gib(report.get('free_bytes_after'))} "
        f"(reserve {gib(report.get('reserve_bytes'))})"
    )
    lines.append("")
    lines.append(f"{'Category':<14}{'Used':>12}{'Ceiling':>12}{'Floor':>8}  Action")

    verb = "Would remove" if (report.get("dry_run") or report.get("report_only")) else "Removed"
    for key, cat in sorted(report.get("categories", {}).items()):
        sweep = cat.get("last_sweep")
        if sweep:
            action = f"{verb} {sweep['files_removed']:,} files ({gib(sweep['bytes_freed'])})"
        elif cat.get("floor_blocked"):
            action = "blocked by floor"
        else:
            action = "nothing to do"
        lines.append(
            f"{key:<14}{gib(cat.get('bytes')):>12}{gib(cat.get('limit_bytes')):>12}"
            f"{str(cat.get('floor_days')) + 'd':>8}  {action}"
        )

    if report.get("manifest_path"):
        lines.append("")
        lines.append(f"Manifest:  {report['manifest_path']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """Run one sweep and publish what it found.

    One shot, then exit. Everything about when this runs lives in the systemd
    timer, so the schedule is an operator's to change with the tools they
    already use for schedules.
    """
    import argparse  # noqa: PLC0415

    from orpheus_common.config import OrpheusConfig  # noqa: PLC0415
    from orpheus_common.logging import setup_logging  # noqa: PLC0415
    from orpheus_common.storage.paths import get_data_root  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="orpheus-storage-sweep",
        description="Enforce Orpheus storage retention across every recording category.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decide everything, delete nothing, and print what would go.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Enforce now, ending the first-run grace early.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    args = parser.parse_args(argv)

    setup_logging("orpheus-storage-sweep")
    if args.json:
        # stdout is a data stream in this mode. Logs interleaved into it would
        # make the output unparseable for the caller that asked for JSON.
        _logs_to_stderr()

    config = OrpheusConfig.get_instance()
    retention = config.storage.retention
    root = get_data_root()
    now = datetime.now().astimezone()

    try:
        lock = _acquire_lock(root)
    except OSError as exc:
        # Not contention — the lock itself is unreachable: an unmounted drive
        # whose bare mountpoint is root-owned, a read-only remount, a data
        # root the orpheus user cannot write. Exiting 0 here would leave a
        # green timer and a stale dashboard on a station where nothing else
        # deletes recordings, so this fails the unit instead.
        logger.critical(
            "Could not take the storage sweep lock, so nothing was measured or "
            "deleted. Nothing else on this station deletes recordings. Check that "
            f"the data root exists and is writable by this service's user. {exc}",
            path=str(root / LOCK_FILENAME),
            error=str(exc),
        )
        return EXIT_ERROR
    if lock is None and not args.dry_run:
        # A dry run reads; it can share the disk with a real sweep. A second
        # enforcing sweep cannot.
        logger.info("Another sweep holds the lock — exiting", path=str(root / LOCK_FILENAME))
        return EXIT_OK

    state = read_state(root)
    try:
        in_grace, installed_at = _grace_state(retention, state, now)
    except (TypeError, ValueError) as exc:
        # A hand-edited state file. Refusing to run is right: without a
        # trustworthy installed_at the sweep cannot tell whether it is still
        # inside the review window, and guessing wrong deletes recordings.
        logger.critical(
            "Could not read the first-run grace from the sweep state file, so "
            "nothing was deleted. Fix or remove it to restart the review window: "
            f"{root / STATE_FILENAME}. {exc}",
            error=str(exc),
        )
        return EXIT_ERROR
    enabled = bool(getattr(retention, "sweep_enabled", True))
    report_only = in_grace and not args.force
    # Measure even when deletion is switched off: an operator who disables the
    # sweep still needs the dashboard to show what is on the disk. Silence
    # would read as "nothing is growing".
    dry_run = args.dry_run or report_only or not enabled

    try:
        sweep = StorageSweep(root, retention)
        result = sweep.run(dry_run=dry_run)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Storage sweep failed", error=str(exc))
        return EXIT_ERROR

    result.report.update(
        {
            "sweep_enabled": enabled,
            "report_only": report_only,
            "installed_at": installed_at,
            # True once the window is over, whether it elapsed or --force ended
            # it early, and sticky thereafter: --force is a decision about this
            # station rather than about one run, so the next timer tick must not
            # revert to report-only.
            #
            # The elapsed half matters for the report rather than for behaviour:
            # the sweep recomputes the window from installed_at every run and
            # was enforcing correctly without it, but a published field called
            # grace_ended read `false` on a station that had been deleting for
            # hours, which is the opposite of what an operator checking it
            # wants to learn.
            "grace_ended": bool((state or {}).get("grace_ended"))
            or (args.force and not args.dry_run)
            or not in_grace,
        }
    )

    if not args.dry_run:
        write_state(root, result.report)

    if not enabled:
        logger.warning(
            "storage.retention.sweep_enabled is false — measured only, deleted nothing. "
            "Nothing else on this station deletes recordings.",
            data_root=str(root),
        )
    elif report_only and result.files_removed:
        logger.critical(
            "First-run grace: this sweep would have removed recordings and did not. "
            f"Review it with `{REVIEW_COMMAND}` and adjust storage.retention if the "
            "ceilings are wrong. Enforcement begins automatically after the grace "
            "window; `orpheus-storage-sweep --force` starts it now.",
            files=result.files_removed,
            gib=round(result.bytes_freed / BYTES_PER_GIB, 2),
            grace_hours=float(getattr(retention, "first_run_grace_hours", 24.0)),
            installed_at=installed_at,
        )
    elif report_only:
        logger.info(
            "First-run grace in effect; nothing is over its ceiling and free space is "
            "above the reserve, so this sweep would have removed nothing.",
            installed_at=installed_at,
        )
    else:
        logger.info(
            "Storage sweep complete",
            files_removed=result.files_removed,
            gib_freed=round(result.bytes_freed / BYTES_PER_GIB, 2),
            free_gib=(
                round(result.report["free_bytes_after"] / BYTES_PER_GIB, 2)
                if result.report.get("free_bytes_after") is not None
                else None
            ),
            reserve_gib=round(result.report["reserve_bytes"] / BYTES_PER_GIB, 2),
            dry_run=dry_run,
        )

    if args.json:
        print(json.dumps(result.report, indent=2, sort_keys=True))
    elif args.dry_run:
        print(_format_summary(result.report))

    return EXIT_BLOCKED if result.blocked_under_reserve else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
