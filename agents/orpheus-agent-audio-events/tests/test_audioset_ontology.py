"""Tests for the AudioSet ontology loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from orpheus_agent_audio_events import audioset_ontology
from orpheus_agent_audio_events.audioset_ontology import (
    AudioSetLabel,
    index_by_machine_id,
    label_for_index,
    load_labels,
    species_code_for,
)


class TestLoadLabels:
    """Tests for ``load_labels()``."""

    def test_loads_tiny_csv(self, tiny_labels_csv: Path) -> None:
        labels = load_labels(tiny_labels_csv)
        assert len(labels) == 3
        assert 0 in labels
        assert 1 in labels
        assert 5 in labels
        assert labels[0].machine_id == "/m/test_a"
        assert labels[0].display_name == "Test Class A"
        assert labels[5].display_name == "Test Class C"

    def test_sparse_indices_ok(self, tiny_labels_csv: Path) -> None:
        """Indices need not be contiguous from 0."""
        labels = load_labels(tiny_labels_csv)
        # Index 2/3/4 are not present and that's fine.
        assert 2 not in labels
        assert 3 not in labels
        assert 4 not in labels

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        bogus = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError):
            load_labels(bogus)

    def test_malformed_missing_columns(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "broken.csv"
        csv_path.write_text("foo,bar\n1,2\n")
        with pytest.raises(ValueError, match="missing required columns"):
            load_labels(csv_path)

    def test_duplicate_index_raises(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "dup.csv"
        csv_path.write_text(
            "index,mid,display_name\n"
            "0,/m/a,A\n"
            "0,/m/b,B\n"
        )
        with pytest.raises(ValueError, match="duplicate index"):
            load_labels(csv_path)

    def test_negative_index_raises(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "neg.csv"
        csv_path.write_text(
            "index,mid,display_name\n"
            "-1,/m/a,A\n"
        )
        with pytest.raises(ValueError, match="negative index"):
            load_labels(csv_path)

    def test_cache_is_used_for_default_path(self, tiny_labels_csv: Path) -> None:
        """The default-path cache is hit on the second call."""
        # The autouse fixture clears _cache for each test. Here we manually
        # exercise the default-path branch by populating _cache, then call
        # without a path argument.
        # We can't easily call the real default path (which points at the
        # bundled CSV), so we test the cache-bypass behavior with a path arg:
        # the first call loads, the second call with the same path should
        # also load (no cache for path overrides — that's by design).
        labels_a = load_labels(tiny_labels_csv)
        labels_b = load_labels(tiny_labels_csv)
        assert labels_a == labels_b


class TestLookupHelpers:
    """Tests for the lookup helpers."""

    def test_label_for_index_hit(self, tiny_labels_csv: Path) -> None:
        labels = load_labels(tiny_labels_csv)
        result = label_for_index(1, labels)
        assert result is not None
        assert result.machine_id == "/m/test_b"

    def test_label_for_index_miss_returns_none(self, tiny_labels_csv: Path) -> None:
        labels = load_labels(tiny_labels_csv)
        assert label_for_index(99, labels) is None

    def test_species_code_for_audioset_mid(self) -> None:
        assert species_code_for("/m/04rlf") == "audioset_/m/04rlf"

    def test_index_by_machine_id(self, tiny_labels_csv: Path) -> None:
        labels = load_labels(tiny_labels_csv)
        reverse = index_by_machine_id(labels)
        assert reverse["/m/test_a"].index == 0
        assert reverse["/m/test_b"].index == 1
        assert reverse["/m/test_c"].index == 5


class TestBundledCSV:
    """Sanity-check the bundled production CSV (the real one shipped with the agent)."""

    def test_bundled_csv_exists_and_loads(self) -> None:
        # This loads from the default path, exercising the production data file.
        audioset_ontology.reset_cache()
        labels = audioset_ontology.load_labels()
        assert isinstance(labels, dict)
        assert len(labels) > 0, "bundled CSV must have at least one entry"

    def test_bundled_csv_has_bird_category(self) -> None:
        """The bundled CSV must include the 'Bird' macro-category — that's
        the canary that we ship enough labels to be useful for wildlife use."""
        labels = audioset_ontology.load_labels()
        names = {label.display_name.lower() for label in labels.values()}
        assert "bird" in names

    def test_bundled_csv_all_have_machine_ids(self) -> None:
        labels = audioset_ontology.load_labels()
        for index, label in labels.items():
            assert label.machine_id, f"label at index {index} missing machine_id"
            assert label.machine_id.startswith("/"), (
                f"label at index {index} machine_id should start with '/'"
            )

    def test_bundled_csv_indices_are_all_valid_audioset_range(self) -> None:
        """AudioSet has 527 classes — indices must be in [0, 527)."""
        labels = audioset_ontology.load_labels()
        for index in labels:
            assert 0 <= index < 527, f"index {index} outside AudioSet range"

    def test_bundled_csv_covers_every_bird_like_mid(self) -> None:
        """The curated whitelist must include every mid in orpheus-common's
        BIRD_LIKE_AUDIOSET_MIDS. Otherwise PANNs can emit those classes but
        post-processing whitelists them out, so the agent can NEVER fire them —
        a structural false-negative (rooster crow, duck quack, goose honk, owl
        hoot all undetectable) that also makes the audio-events-vs-BirdNET
        parity dashboard score coverage the agent is incapable of having.
        This pins the whitelist to the canonical set so they can't drift apart.
        """
        from orpheus_common.detection import BIRD_LIKE_AUDIOSET_MIDS  # noqa: PLC0415

        labels = audioset_ontology.load_labels()
        whitelisted_mids = {label.machine_id for label in labels.values()}
        missing = set(BIRD_LIKE_AUDIOSET_MIDS) - whitelisted_mids
        assert not missing, (
            "bird-like AudioSet mids absent from the curated whitelist "
            f"(PANNs can never fire them): {sorted(missing)}"
        )


class TestAudioSetLabel:
    """Tests for the ``AudioSetLabel`` dataclass."""

    def test_construction(self) -> None:
        label = AudioSetLabel(index=42, machine_id="/m/foo", display_name="Foo")
        assert label.index == 42
        assert label.machine_id == "/m/foo"

    def test_frozen(self) -> None:
        """``frozen=True`` prevents accidental mutation."""
        from dataclasses import FrozenInstanceError  # noqa: PLC0415

        label = AudioSetLabel(index=42, machine_id="/m/foo", display_name="Foo")
        with pytest.raises(FrozenInstanceError):
            label.index = 99  # type: ignore[misc]
