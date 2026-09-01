"""AudioSet 527-class ontology mapping for the audio-events agent.

PANNs models emit a 527-dim score vector per frame in AudioSet class-index
order. This module maps those indices to the canonical machine_ids (Freebase
``/m/...`` IDs) and human-readable display names from the AudioSet ontology.

The mapping ships as a sparse CSV at
``data/audioset_class_labels_indices.csv`` — only the indices we have curated
labels for are present. Indices PANNs emits but we don't have a label for are
silently dropped in post-processing (the user sees coarser tagging, not a
crash). Production deployments can expand the CSV by running ``make
download-full-audioset-labels`` (which fetches the canonical 527-row file
from the PANNs release).

License: the AudioSet ontology is CC BY-SA 4.0 (Google). See
``data/AUDIOSET_LICENSE.md``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioSetLabel:
    """A single AudioSet class — index, machine_id, and display name.

    ``machine_id`` (e.g. ``/m/04rlf``) is the canonical Freebase / Knowledge
    Graph identifier and the value downstream consumers should rely on for
    equality / lookup. ``display_name`` is the human-readable label.
    """

    index: int
    machine_id: str
    display_name: str


def _data_path() -> Path:
    """Return the path to the bundled CSV."""
    return Path(__file__).parent / "data" / "audioset_class_labels_indices.csv"


_cache: dict[int, AudioSetLabel] | None = None


def load_labels(path: Path | None = None) -> dict[int, AudioSetLabel]:
    """Load the AudioSet labels keyed by class index.

    The mapping may be sparse — indices PANNs emits that are absent from the
    CSV are not in the returned dict. Callers must handle ``KeyError`` /
    ``in`` checks for missing indices.

    Memoised after first call when ``path`` is the default.

    Args:
        path: Override the default data file path (used by tests).

    Returns:
        ``Dict[int, AudioSetLabel]`` keyed on class index.

    Raises:
        FileNotFoundError: If the CSV is missing.
        ValueError: If the CSV is malformed (missing columns, duplicate index,
            negative index).
    """
    global _cache  # noqa: PLW0603 — intentional module-level cache
    if path is None and _cache is not None:
        return _cache

    csv_path = path if path is not None else _data_path()
    if not csv_path.exists():
        raise FileNotFoundError(
            f"AudioSet labels CSV missing at {csv_path}. "
            "Expected columns: index, mid, display_name."
        )

    labels: dict[int, AudioSetLabel] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"index", "mid", "display_name"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"AudioSet labels CSV at {csv_path} missing required columns "
                f"{required}; got {reader.fieldnames}."
            )
        for row in reader:
            idx = int(row["index"])
            if idx < 0:
                raise ValueError(
                    f"AudioSet labels CSV has negative index {idx} at row "
                    f"{len(labels)}."
                )
            if idx in labels:
                raise ValueError(
                    f"AudioSet labels CSV has duplicate index {idx} at row "
                    f"{len(labels)}."
                )
            labels[idx] = AudioSetLabel(
                index=idx,
                machine_id=row["mid"].strip(),
                display_name=row["display_name"].strip(),
            )

    if path is None:
        _cache = labels
    return labels


def reset_cache() -> None:
    """Clear the memoised labels dict. Used by tests."""
    global _cache  # noqa: PLW0603
    _cache = None


def label_for_index(
    index: int, labels: dict[int, AudioSetLabel] | None = None
) -> AudioSetLabel | None:
    """Look up an AudioSetLabel by class index.

    Args:
        index: Class index from the model's output vector.
        labels: Optional pre-loaded dict (avoids reloading in hot paths).

    Returns:
        The ``AudioSetLabel`` for that index, or ``None`` if not in the
        loaded label set.
    """
    table = labels if labels is not None else load_labels()
    return table.get(index)


def species_code_for(machine_id: str) -> str:
    """Build a ``Detection.species_code`` value for an AudioSet machine_id.

    The convention is ``audioset_<machine_id>`` so the correlator's alias map
    (see "[CORE] Correlator Alias Map" backlog issue) can keyed-merge across
    classifiers.
    """
    return f"audioset_{machine_id}"


def index_by_machine_id(
    labels: dict[int, AudioSetLabel] | None = None,
) -> dict[str, AudioSetLabel]:
    """Build a reverse lookup map ``machine_id → AudioSetLabel``."""
    table = labels if labels is not None else load_labels()
    return {label.machine_id: label for label in table.values()}
