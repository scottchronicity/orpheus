"""Per-category storage headroom, assembled from the last retention sweep.

The Storage-trend card answers "is the disk filling". This answers the two
questions you ask next: how much is each kind of recording using, and which
of those will be trimmed automatically.

Those are separate questions and the payload keeps them separate. Every
category has a size, because ``orpheus-storage-sweep`` surveys the whole data
root on every run. Only some categories have a ceiling, and those come from
the same run that would enforce it. The second list being shorter than the
first is simply the fact — the detections database is measured and never
swept — and a card assembled only from cleanup reports would have left the
unswept directories out entirely, which is exactly where the surprises are.

Nothing here walks the filesystem. The sweep already walks it every few
minutes and already holds the policy, so this module reads the report it
published and serves it with the timestamp of the run that measured it. A
dashboard that scanned for itself would duplicate a walk over a
quarter-million files and become a second, disagreeing source of truth.

This used to read the motion agents' health payloads, back when each agent
trimmed its own directory. It reads one report now because there is one
deleter now; see ``docs/designs/storage-retention.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.storage import DATA_ROOT_CATEGORIES, get_data_root, read_state

# How far past the sweep cadence a report may fall before the panel stops
# presenting it as current. Three intervals rather than one: a single missed
# tick is a slow walk or a reboot, not a fault, and an amber panel that cries
# wolf gets ignored exactly when it matters.
STALE_INTERVALS = 3


def _sweep_state(
    report: Optional[dict[str, Any]],
    *,
    measured_at: Optional[str] = None,
    interval_minutes: float = 15.0,
    now: Optional[datetime] = None,
) -> str:
    """What the sweep is doing right now, in one word for the panel.

    An operator's first question about a retention component is whether it is
    actually deleting anything. Every state below except ``enforcing`` means
    it is not, and each has a different remedy, so they are not collapsed
    into one "inactive".

    ``stale`` outranks the rest because the report only changes when a sweep
    succeeds. A sweep that has stopped therefore leaves its last good report
    in place forever, and without this check the panel would go on rendering
    week-old bars labelled "enforcing" — the one failure a retention dashboard
    exists to catch, and the one it could not previously show.
    """
    if not report:
        return "never_run"

    stamp = measured_at or report.get("swept_at")
    if stamp:
        try:
            measured = datetime.fromisoformat(str(stamp))
        except ValueError:
            measured = None
        if measured is not None:
            current = now or datetime.now().astimezone()
            if measured.tzinfo is None:
                measured = measured.astimezone()
            age_minutes = (current - measured).total_seconds() / 60
            if age_minutes > max(interval_minutes, 1.0) * STALE_INTERVALS:
                return "stale"

    if not report.get("sweep_enabled", True):
        return "disabled"
    if report.get("report_only"):
        return "report_only"
    return "enforcing"


def build_headroom_payload(report: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Assemble the API shape from the sweep's published report.

    ``report`` is the sweep's state file, or ``None`` when the sweep has not
    run yet — a fresh install, or a station where the timer is not enabled.
    Read from disk when not supplied.
    """
    config = OrpheusConfig.get_instance()
    retention = config.storage.retention
    root = get_data_root()

    if report is None:
        report = read_state(root)

    survey = (report or {}).get("survey") or {}
    measured = survey.get("categories") or {}
    swept = (report or {}).get("categories") or {}
    swept_at = (report or {}).get("swept_at")

    categories: list[dict[str, Any]] = []

    for spec in DATA_ROOT_CATEGORIES:
        sizes = measured.get(spec.key) or {}
        policy = swept.get(spec.key)

        entry: dict[str, Any] = {
            "key": spec.key,
            "label": spec.label,
            "description": spec.description,
            "path": sizes.get("path") or str(root / spec.relative_path),
            # Size is known for every category, or for none of them (the
            # sweep has not run). Never a zero standing in for unknown.
            "measured": bool(sizes),
            "bytes": sizes.get("bytes"),
            "file_count": sizes.get("file_count"),
            # Policy is the separate question, and not every category has one.
            "has_policy": False,
            "policy_kind": None,
            "limit_bytes": None,
            "percent_of_limit": None,
            "trigger_percent": None,
            "retention_days": None,
            "policy_note": None,
            "last_sweep": None,
            "would_remove": None,
        }

        if policy is not None:
            last = policy.get("last_sweep")
            forecast = policy.get("would_remove")
            floor_days = policy.get("floor_days")
            # A note only where there is something a reader would not infer
            # from the numbers. The one such case is a ceiling the floor will
            # not let the sweep reach — the panel would otherwise show a
            # category parked over its limit with nothing explaining why.
            note = None
            if policy.get("floor_blocked"):
                limit_gib = (policy.get("limit_bytes") or 0) / (1024**3)
                # Ceilings are normally hundreds of GiB, but a test rig or a
                # deliberately tiny one must not render as "0 GiB".
                shown = f"{limit_gib:,.0f}" if limit_gib >= 10 else f"{limit_gib:,.2f}"
                note = (
                    f"Over its {shown} GiB ceiling, but everything it still "
                    f"holds is inside the {floor_days}-day floor. Nothing further "
                    "will be deleted until the floor or the ceiling changes."
                )

            entry.update(
                {
                    "has_policy": True,
                    "policy_kind": "size_budget",
                    "limit_bytes": policy.get("limit_bytes"),
                    "percent_of_limit": policy.get("percent_of_limit"),
                    "trigger_percent": policy.get("trigger_percent"),
                    "retention_days": floor_days,
                    "policy_note": note,
                    # The sweep records what it removed; the timestamp of the
                    # run is what makes that legible, so it is folded in here.
                    "last_sweep": {**last, "at": swept_at} if last else None,
                    # What a sweep would remove if it were enforcing. Present
                    # instead of last_sweep during the grace and whenever the
                    # sweep is switched off, so the panel can say "would" and
                    # never reports a deletion that did not happen.
                    "would_remove": {**forecast, "at": swept_at} if forecast else None,
                }
            )

        categories.append(entry)

    disk = survey.get("disk") or {}
    reserve_bytes = (report or {}).get("reserve_bytes")
    filesystem: dict[str, Any] = {
        "total_bytes": disk.get("total_bytes"),
        "free_bytes": disk.get("free_bytes"),
        "free_percent": disk.get("free_percent"),
        "min_free_space_percent": retention.min_free_space_percent,
        # What the sweep actually works to keep free, after reconciling
        # reserve_gb with min_free_space_percent. The bytes are the honest
        # figure: a percentage of an unknown disk is not runway.
        "reserve_bytes": reserve_bytes,
        # 0 disables the guard entirely — the UI must say "off", not "0 B".
        "guard_enabled": bool(reserve_bytes),
        "guard_tripped": bool((report or {}).get("guard_tripped")),
        # Under the reserve with every category at its floor. The one storage
        # condition that needs a person.
        "blocked_under_reserve": bool((report or {}).get("blocked_under_reserve")),
    }

    return {
        "data_root": str(root),
        # When the sizes were measured; None when the sweep has never run.
        "measured_at": survey.get("measured_at"),
        # The sweep cadence, so a stale timestamp reads as expected rather
        # than as something broken.
        "check_interval_hours": retention.sweep_interval_minutes / 60,
        "sweep_state": _sweep_state(
            report,
            measured_at=survey.get("measured_at"),
            interval_minutes=retention.sweep_interval_minutes,
        ),
        "categories": categories,
        "filesystem": filesystem,
    }
